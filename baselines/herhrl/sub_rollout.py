import numpy as np
import time

from baselines.template.util import store_args
from baselines.template.util import logger as log_formater
from baselines.template.rollout import Rollout
from tqdm import tqdm
from collections import deque
from baselines.template.util import convert_episode_to_batch_major

class RolloutWorker(Rollout):

    @store_args
    def __init__(self, make_env, policy, dims, logger, rollout_batch_size=1,
                 exploit=False, history_len=200, render=False, **kwargs):
        """Rollout worker generates experience by interacting with one or many environments.

        Args:
            make_env (function): a factory function that creates a new instance of the environment
                when called
            policy (object): the policy that is used to act
            dims (dict of ints): the dimensions for observations (o), goals (g), and actions (u)
            logger (object): the logger that is used by the rollout worker
            rollout_batch_size (int): the number of parallel rollouts that should be used
            exploit (boolean): whether or not to exploit, i.e. to act optimally according to the
                current policy without any exploration
            use_target_net (boolean): whether or not to use the target net for rollouts
            compute_Q (boolean): whether or not to compute the Q values alongside the actions
            noise_eps (float): scale of the additive Gaussian noise
            random_eps (float): probability of selecting a completely random action
            history_len (int): length of history for statistics smoothing
            render (boolean): whether or not to render the rollouts
        """
        self.exploit = exploit
        self.is_leaf = policy.child_policy is None
        self.h_level = policy.h_level
        dims = policy.input_dims
        self.rep_correct_history = deque(maxlen=history_len)
        self.q_loss_history = deque(maxlen=history_len)
        self.pi_loss_history = deque(maxlen=history_len)
        self.q_history = deque(maxlen=history_len)
        if self.is_leaf is False:
            self.child_rollout = RolloutWorker(make_env, policy.child_policy, dims, logger,
                                               rollout_batch_size=rollout_batch_size,
                                               render=render, **kwargs)

        # Envs are generated only at the lowest hierarchy level. Otherwise just refer to the child envs.
        if self.is_leaf is False:
            make_env = self.make_env_from_child
        self.tmp_env_ctr = 0
        Rollout.__init__(self, make_env, policy, dims, logger,
                         rollout_batch_size=rollout_batch_size,
                         history_len=history_len, render=render, **kwargs)
        self.this_T = policy.T
        self.env_name = self.envs[0].env.spec._env_name
        self.n_objects = self.envs[0].env.n_objects
        self.gripper_has_target = self.envs[0].env.gripper_goal != 'gripper_none'
        self.tower_height = self.envs[0].env.goal_tower_height

    def make_env_from_child(self):
        env = self.child_rollout.envs[self.tmp_env_ctr]
        self.tmp_env_ctr += 1
        return env

    def train_policy(self, n_train_batches):
        q_losses, pi_losses = [], []
        for _ in range(n_train_batches):
            q_loss, pi_loss = self.policy.train()  # train actor-critic
            q_losses.append(q_loss)
            pi_losses.append(pi_loss)
        if n_train_batches > 0:
            self.policy.update_target_net()
            if not self.is_leaf:
                self.child_rollout.train_policy(n_train_batches)
            self.q_loss_history.append(np.mean(q_losses))
            self.pi_loss_history.append(np.mean(pi_losses))

    def init_rollout(self, obs, i):
        self.initial_o[i] = obs['observation']
        self.initial_ag[i] = obs['achieved_goal']
        self.g[i] = obs['desired_goal']
        if self.is_leaf == False:
            self.child_rollout.init_rollout(obs, i)

    def reset_rollout(self, i):
        """Resets the `i`-th rollout environment, re-samples a new goal, and updates the `initial_o`
        and `g` arrays accordingly.
        """
        if self.h_level == 0:
            obs = self.envs[i].reset()
            self.init_rollout(obs, i)

    def generate_rollouts(self, return_states=False):
        '''
        Overwrite generate_rollouts function from Rollout class with hierarchical rollout function that supports subgoals.
        :param return_states:
        :return:
        '''
        if self.h_level == 0:
            self.reset_all_rollouts()
        for i, env in enumerate(self.envs):
            if self.is_leaf:
                self.envs[i].env.goal = self.g[i].copy()
            if self.h_level == 0:
                self.envs[i].env.final_goal = self.g[i].copy()
            self.envs[i].env.goal_hierarchy[self.h_level] = self.g[i].copy()

        # compute observations
        o = np.empty((self.rollout_batch_size, self.dims['o']), np.float32)  # observations
        ag = np.empty((self.rollout_batch_size, self.dims['g']), np.float32)  # achieved goals
        o[:] = self.initial_o
        ag[:] = self.initial_ag

        # hold custom histories through out the iterations
        # other_histories = []

        # generate episodes
        obs, achieved_goals, acts, goals, successes = [], [], [], [], []

        info_values = [np.empty((self.this_T, self.rollout_batch_size, self.dims['info_' + key]), np.float32) for key in
                       self.info_keys]
        child_episodes = None
        for t in range(self.this_T):

            u, q = self.policy.get_actions(o, ag, self.g, **self.policy_action_params)
            o_new = np.empty((self.rollout_batch_size, self.dims['o']))
            ag_new = np.empty((self.rollout_batch_size, self.dims['g']))
            success = np.zeros(self.rollout_batch_size)
            self.q_history.append(np.mean(q))
            if self.is_leaf is False:
                if t == self.this_T-1:
                    u = self.g.copy()  # For last step use final goal
                else:
                    assert self.h_level == 1

                self.child_rollout.g = u
                self.child_rollout.generate_rollouts_update(n_episodes=1, n_train_batches=0,
                                                            store_episode=(self.exploit == False),
                                                            return_episodes=True)
                child_successes = np.array(child_episodes[0]['info_is_success'])[:, -1]
                child_goal = child_episodes[0]['g'][:,-1,:]
                if str(child_goal) != str(self.g):
                    print(child_goal)
                    print('---')
                    print(self.g)
                    print('---')
                    print(self.child_rollout.g)
                    print('Not good!')

                # print(child_successes)
            # compute new states and observations
            for i in range(self.rollout_batch_size):
                # We fully ignore the reward here because it will have to be re-computed
                # for HER.
                if self.is_leaf:
                    curr_o_new, _, _, info = self.envs[i].step(u[i])
                else:
                    curr_o_new = self.envs[i].env._get_obs()
                    this_ag = curr_o_new['achieved_goal']
                    this_success = self.envs[i].env._is_success(this_ag, self.g[i])
                    info = {'is_success': this_success}
                if 'is_success' in info:
                    success[i] = info['is_success']
                o_new[i] = curr_o_new['observation']
                ag_new[i] = curr_o_new['achieved_goal']
                for idx, key in enumerate(self.info_keys):
                    info_values[idx][t, i] = info[key]
                if self.render:
                    self.envs[i].render()

            obs.append(o.copy())
            achieved_goals.append(ag.copy())
            successes.append(success.copy())
            acts.append(u.copy())
            goals.append(self.g.copy())
            o[...] = o_new
            ag[...] = ag_new
        obs.append(o.copy())
        achieved_goals.append(ag.copy())

        self.initial_o[:] = o
        episode = dict(o=obs,
                       u=acts,
                       g=goals,
                       ag=achieved_goals)
        for key, value in zip(self.info_keys, info_values):
            episode['info_{}'.format(key)] = value

        # stats
        successful = np.array(successes)[-1, :]
        assert successful.shape == (self.rollout_batch_size,)
        success_rate = np.mean(successful)
        self.success_history.append(success_rate)
        self.n_episodes += self.rollout_batch_size

        ret = convert_episode_to_batch_major(episode)
        return ret


    def generate_rollouts_update(self, n_episodes, n_train_batches, store_episode=True, return_episodes=False):
        # Make sure that envs of policy are those of the respective rollout worker. Important, because otherwise envs of evaluator and worker will be confused.
        self.policy.set_envs(self.envs)
        dur_ro = 0
        dur_train = 0
        dur_start = time.time()
        rep_ce_loss = 0
        if return_episodes:
            all_episodes = []
        for cyc in tqdm(range(n_episodes), disable=self.h_level > 0):
            ro_start = time.time()
            episode = self.generate_rollouts()
            if store_episode:
                self.policy.store_episode(episode)
            dur_ro += time.time() - ro_start
            train_start = time.time()
            self.train_policy(n_train_batches)
            dur_train += time.time() - train_start
            if return_episodes:
                all_episodes.append(episode)
        dur_total = time.time() - dur_start
        updated_policy = self.policy
        time_durations = (dur_total, dur_ro, dur_train)
        if return_episodes:
            ret = updated_policy, time_durations, all_episodes
        else:
            ret = updated_policy, time_durations
        return ret

    def current_mean_Q(self):
        return np.mean(self.custom_histories[0])

    def logs(self, prefix='worker'):
        """Generates a dictionary that contains all collected statistics.
        """
        logs = []
        logs += [('success_rate', np.mean(self.success_history))]
        if self.custom_histories:
            logs += [('mean_Q', np.mean(self.custom_histories[0]))]
        if len(self.q_loss_history) > 0 and len(self.pi_loss_history) > 0:
            logs += [('q_loss', np.mean(self.q_loss_history))]
            logs += [('pi_loss', np.mean(self.pi_loss_history))]
        # logs += [('episode', self.n_episodes)]
        # if len(self.rep_loss_history) > 0:
        #     logs += [('rep_ce_loss', np.mean(self.rep_loss_history))]
        # if len(self.rep_correct_history) > 0:
        #     logs += [('rep_correct', np.mean(self.rep_correct_history))]
        # logs += [('episode', self.n_episodes)]
        logs += [('mean_Q', np.mean(self.q_history))]
        logs = log_formater(logs, prefix+"_{}".format(self.h_level))

        if self.is_leaf is False:
            child_logs = self.child_rollout.logs(prefix=prefix)
            logs += child_logs

        return logs

    def clear_history(self):
        """Clears all histories that are used for statistics
        """
        self.success_history.clear()
        self.custom_histories.clear()
        self.q_history.clear()
        self.pi_loss_history.clear()
        self.q_loss_history.clear()
        self.rep_correct_history.clear()
        if self.is_leaf is False:
            self.child_rollout.clear_history()