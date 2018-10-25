import threading
import random
import numpy as np
from collections import deque


class ModelReplayBuffer:
    def __init__(self, buffer_shapes, size):
        """Creates a replay buffer to train the model.

        Args:
            size (int): the size of the buffer, measured in rollouts
            sample (function): a function that samples episodes from the replay buffer
        """
        self.size = size

        self.buffers = {}
        n_steps = None
        for key, shape in buffer_shapes.items():
            if n_steps == None:
                n_steps = shape[1]
            else:
                # Number of steps per rollout must always be equal.
                assert n_steps == shape[1]
            dim = shape[2]
            self.buffers[key] = np.empty([self.size, n_steps, dim])

        # For each replay rollout, stores the value of keeping this rollout in memory.
        self.memory_value = np.zeros([self.size])

        # For each replay rollout, stores the loss_history
        self.loss_history = np.zeros([self.size, n_steps])

        # This initial mujoco simulation states. Required for visualizing the experience replay.
        self.initial_mj_states = list(np.zeros([self.size]))

        # For each replay rollout, stores the episode at which it was stored.
        self.ep_added = np.zeros([self.size])

        # Incremental counter to count the number of episodes.
        self.ep_no = 0

        # memory management
        self.current_size = 0

        self.lock = threading.Lock()

    @property
    def full(self):
        with self.lock:
            return self.current_size == self.size

    def update_with_loss(self, idxs, losses):
        with self.lock:
            for l, idx in zip(losses, idxs):
                self.loss_history[idx] = l
                self.memory_value[idx] = np.max(l)

        pass

    def recompute_memory_values(self):
        with self.lock:
            for idx in range(len(self.memory_value)):
                # age = self.ep_no - self.ep_added[idx]
                # if age == 0:
                #     age_factor = 1
                # else:
                #     age_factor = self.ep_no / age
                age_factor = self.ep_added[idx] / self.ep_no
                self.memory_value[idx] = max(self.loss_history[idx]) * age_factor



    def sample(self, batch_size=None, idxs=None):
        """Returns a dict {key: array(batch_size x shapes[key])}
        """
        assert not (batch_size is None and idxs is None)
        if batch_size is None:
            batch_size = len(idxs)
        # buffers = {}
        batch = {}
        for key in self.buffers.keys():
            batch[key] = np.zeros((batch_size, self.buffers[key].shape[1], self.buffers[key].shape[2]))
        if self.current_size == 0:
            return batch

        with self.lock:
            assert self.current_size > 0
            replace = self.current_size < self.size
            if idxs is not None:
                sample_idxs = idxs
            else:
                sample_idxs = np.random.choice(self.current_size, batch_size, replace=replace)
            for b_idx,idx in enumerate(sample_idxs):
                for key in self.buffers.keys():
                    batch[key][b_idx] = self.buffers[key][idx]

        return batch, sample_idxs

    def store_episode(self, episode, initial_mj_states=None):
        """episode_batch: array(batch_size x (T or T+1) x dim_key)
        """
        idxs = []
        with self.lock:
            self.ep_no += 1
            space_left = self.size - self.current_size
            for _ in range(space_left):
                ins_idx = self.current_size
                idxs.append(ins_idx)
                self.current_size += 1
                if len(idxs) >= len(episode):
                    break

            n_remaining_idxs = len(episode) - len(idxs)

            if n_remaining_idxs > 0:
                # select indexes of replay buffer with lowest memory values.
                replacement_idxs = self.memory_value.argsort()[:n_remaining_idxs]

                idxs += list(replacement_idxs)

            for buf_idx, ro, ro_idx in zip(idxs, episode, range(len(episode))):
                for key in ro.keys():
                    self.buffers[key][buf_idx] = ro[key]
                self.ep_added[buf_idx] = self.ep_no
                if initial_mj_states is not None:
                    self.initial_mj_states[buf_idx] = initial_mj_states[ro_idx]

        return idxs

    # def display_buffer_stats(self):
    #     # Total buffer age
    #     # Average episode age
    #     # Episode age distribution
    #     # Age vs. surprisal
    #     # Average memory value
    #     # Latest experience older than X.
    #
    #     print(self.current_size)

    def get_latest_stored_experiences(self):
        latest_idxs = np.argwhere(self.ep_added == max(self.ep_added) and self.ep_added < self.ep_no)

        return latest_idxs



