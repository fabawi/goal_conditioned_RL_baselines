import numpy as np
import time, datetime
from baselines.template.util import store_args
from baselines.template.util import logger as log_formater
from baselines.template.rollout import Rollout
from baselines.her.rollout import RolloutWorker as HER_RolloutWorker
from collections import deque
import numpy as np
import pickle
import copy
from mujoco_py import MujocoException
from baselines.template.util import convert_episode_to_batch_major, store_args
from tqdm import tqdm

class HierarchicalRollout(Rollout):

    @store_args
    def __init__(self, make_env, policy, dims, logger, rollout_batch_size=1,
                 exploit=False, render=False, **kwargs):

        self.is_leaf = policy.child_policy is None
        dims = policy.input_dims
        self.T = policy.T
        # TODO: set history_len appropriately, such that it is reset after each epoch and takes exactly the number of episodes per epoch for each layer.
        history_len = 50
        if self.is_leaf is False:
            self.child_rollout = RolloutWorker(make_env, policy.child_policy, dims, logger,
                                                h_level=self.h_level+1,
                                                rollout_batch_size=rollout_batch_size,
                                                render=render, **kwargs)

        # Envs are generated only at the lowest hierarchy level. Otherwise just refer to the child envs.
        if self.is_leaf is False:
            make_env = self.make_env_from_child
        self.tmp_env_ctr = 0
        Rollout.__init__(self, make_env, policy, dims, logger, self.T,
                         rollout_batch_size=rollout_batch_size,
                         history_len=history_len, render=render, **kwargs)

        self.env_name = self.envs[0].env.spec._env_name
        self.n_objects = self.envs[0].env.n_objects
        self.gripper_has_target = self.envs[0].env.gripper_goal != 'gripper_none'
        self.tower_height = self.envs[0].env.goal_tower_height
        self.rep_correct_history = deque(maxlen=history_len)

    def make_env_from_child(self):
        env = self.child_rollout.envs[self.tmp_env_ctr]
        self.tmp_env_ctr += 1
        return env

    def generate_rollouts(self, return_states=False):
        '''
        Overwrite generate_rollouts function from Rollout class with hierarchical rollout function that supports subgoals.
        :param return_states:
        :return:
        '''
        return self.generate_rollouts_hierarchical(return_states=return_states)

    def generate_rollouts_hierarchical(self, return_states=False):
        """Performs `rollout_batch_size` rollouts in parallel for time horizon `T` with the current
        policy acting on it accordingly.
        """

        """ ==================== Step 1: initialize s0, s1, goal =================================
        """
        if self.h_level == 0:
            self.reset_all_rollouts()

        # Setting subgoal and goal to environment, for visualization purpose
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

        # hold custom histories throughout the iterations
        other_histories = []

        # generate episodes
        obs, achieved_goals, acts, goals, successes, penalties = [], [], [], [], [], []
        info_values = [np.empty((self.T, self.rollout_batch_size, self.dims['info_' + key]), np.float32) for key
                       in self.info_keys]

        for t_parent in range(self.T):

            ''' =========================== Step 2: Sampling action a1 <-- policy pi1(s1, goal) ========================
            - if not testing: add_noise to get_action if random_sample()>0.2 otherwise get_random_action
            - if testing: get_action
            '''
            u = self.policy.get_actions(o, ag, self.g, **self.policy_action_params)
            o_new = np.empty((self.rollout_batch_size, self.dims['o']))
            ag_new = np.empty((self.rollout_batch_size, self.dims['g']))
            success = np.zeros(self.rollout_batch_size)
            penalty = np.zeros(self.rollout_batch_size)
            """ ============================== Step 3: Setting subgoal g0 = subg1 <-- action a1 ========================
            """
            if self.is_leaf is False:
                if t_parent == self.T-1:
                    u = self.g.copy()  # For testing use final goal
                self.child_rollout.g = u
                self.child_rollout.generate_rollouts_update(n_episodes=1, n_train_batches=0)
            for i in range(self.rollout_batch_size):
                info = {}
                if self.is_leaf:
                    curr_o_new, _, _, info = self.envs[i].step(u[i])
                    o_new[i] = curr_o_new['observation']
                    ag_new[i] = curr_o_new['achieved_goal']
                else:
                    curr_o_new = self.envs[i].env._get_obs()
                    # TODO: Fix penalty computation and realize penalties during training
                    penalty[i] = False
                    o_new[i] = curr_o_new['observation']
                    ag_new[i] = curr_o_new['achieved_goal']
                    info['is_success'] = self.envs[i].env._is_success(ag_new[i], self.g[i])

                success[i] = info['is_success']

                for idx, key in enumerate(self.info_keys):
                    info_values[idx][t_parent, i] = info[key]
                if self.render and self.is_leaf:
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

        success_rate = np.mean(successes[-1])
        # if success_rate > 0:
        #     print('h {}: succ: {} '.format(self.h_level, success_rate))
        #     print('yay!')
        self.success_history.append(success_rate)

        # history --> mean_Q
        if other_histories:
            for history_index in range(len(other_histories[0])):
                self.custom_histories.append(deque(maxlen=self.history_len))
                self.custom_histories[history_index].append([x[history_index] for x in other_histories])
        self.n_episodes += self.rollout_batch_size

        ret = convert_episode_to_batch_major(episode)

        """ =============== Step 8: Add penalized transition if subgoal_success doesn't have any positive value=========
        """
        return ret


class RolloutWorker(HierarchicalRollout):

    @store_args
    def __init__(self, make_env, policy, dims, logger, T=None, rollout_batch_size=1,
                 exploit=False, h_level=0, render=False, **kwargs):
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
        self.h_level = h_level
        HierarchicalRollout.__init__(self, make_env, policy, dims, logger, rollout_batch_size=rollout_batch_size, render=render, **kwargs)
        self.rep_loss_history = []

    def save_policy(self, path):
        """Pickles the current policy for later inspection.
        """
        with open(path, 'wb') as f:
            pickle.dump(self.policy, f)

    def train_policy(self, n_train_batches):
        for _ in range(n_train_batches):
            self.policy.train()  # train actor-critic
        if n_train_batches > 0:
            self.policy.update_target_net()
            if not self.is_leaf:
                self.child_rollout.train_policy(n_train_batches)

    def generate_rollouts_update(self, n_episodes, n_train_batches):
        # Make sure that envs of policy are those of the respective rollout worker. Important, because otherwise envs of evaluator and worker will be confused.
        self.policy.set_envs(self.envs)
        dur_ro = 0
        dur_train = 0
        dur_start = time.time()
        rep_ce_loss = 0
        for cyc in tqdm(range(n_episodes), disable=self.h_level > 0):
            ro_start = time.time()
            episode = self.generate_rollouts()
            self.policy.store_episode(episode)
            dur_ro += time.time() - ro_start
            train_start = time.time()
            self.train_policy(n_train_batches)
            dur_train += time.time() - train_start
        dur_total = time.time() - dur_start
        updated_policy = self.policy
        time_durations = (dur_total, dur_ro, dur_train)
        # if n_episodes > 0 and n_train_batches > 0:
        #     rep_ce_loss /= (n_train_batches * n_episodes)
        # else:
        #     rep_ce_loss = np.nan
        # self.rep_loss_history.append(rep_ce_loss)
        return updated_policy, time_durations

    def current_mean_Q(self):
        return np.mean(self.custom_histories[0])

    def logs(self, prefix='worker'):
        """Generates a dictionary that contains all collected statistics.
        """
        logs = []
        logs += [('success_rate', np.mean(self.success_history))]
        if self.custom_histories:
            logs += [('mean_Q', np.mean(self.custom_histories[0]))]
        # logs += [('episode', self.n_episodes)]
        # if len(self.rep_loss_history) > 0:
        #     logs += [('rep_ce_loss', np.mean(self.rep_loss_history))]
        # if len(self.rep_correct_history) > 0:
        #     logs += [('rep_correct', np.mean(self.rep_correct_history))]
        # logs += [('episode', self.n_episodes)]
        logs = log_formater(logs, prefix+"_{}".format(self.h_level))

        if self.is_leaf is False:
            child_logs = self.child_rollout.logs(prefix=prefix)
            logs += child_logs

        return logs
