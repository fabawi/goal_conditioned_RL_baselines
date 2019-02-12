import numpy as np
from queue import deque
import tensorflow as tf

class Obs2PredsModel():
    def __init__(self, n_preds, dim_o, dim_g):
        with tf.variable_scope('obs2preds'):
            self.inputs_o = tf.placeholder(shape=[None, dim_o], dtype=tf.float32)
            self.inputs_g = tf.placeholder(shape=[None, dim_g], dtype=tf.float32)
            self.preds = tf.placeholder(shape=[None, n_preds, 2], dtype=tf.uint8)
            in_layer = tf.concat([self.inputs_o, self.inputs_g], axis=1)
            outputs = self.dense_layers(in_layer, [64, 128, n_preds * 2], name='obs2preds_nn')
            outputs = tf.reshape(outputs, [-1, n_preds, 2])
            self.prob_out = tf.nn.softmax(outputs)
            self.celoss = tf.losses.softmax_cross_entropy(self.preds, self.prob_out)
            self.optimizer = tf.train.AdamOptimizer().minimize(self.celoss)
        obs2preds_vars = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope='obs2preds')

        tf.variables_initializer(obs2preds_vars).run()


    def dense_layers(self, input, layers_sizes, reuse=None, flatten=False, name=""):
        """Creates a simple neural network
        """
        for i, size in enumerate(layers_sizes):
            activation = tf.nn.relu if i < len(layers_sizes) - 1 else None
            input = tf.layers.dense(inputs=input,
                                    units=size,
                                    kernel_initializer=tf.contrib.layers.xavier_initializer(),
                                    reuse=reuse,
                                    name=name + '_' + str(i))
            if activation:
                input = activation(input)
        if flatten:
            assert layers_sizes[-1] == 1
            input = tf.reshape(input, [-1])
        return input


class Obs2PredsMem():
    def __init__(self):
        self.buffer_len = 10000
        self.sample_buffer = None
        self.current_buf_size = 0
        self.obs2preds_model = None


    def init_buffer(self, n_preds, dim_o, dim_g):
        p = np.zeros(shape=[self.buffer_len, n_preds])
        self.sample_buffer = {"preds": np.zeros(shape=[self.buffer_len, n_preds]),
                                    "preds_probdist": np.zeros(shape=[self.buffer_len, n_preds, 2]),
                                    "obs": np.zeros(shape=[self.buffer_len, dim_o]),
                                    "goal": np.zeros(shape=[self.buffer_len, dim_g])}
        self.obs2preds_model = Obs2PredsModel(n_preds, dim_o, dim_g)


    def store_sample(self, preds, obs, goal):
        if self.sample_buffer is None:
            self.init_buffer(len(preds), len(obs), len(goal))

        preds_probdist = np.zeros(shape=[len(preds), 2])
        for i,v in enumerate(preds):
            preds_probdist[i][v] = 1

        if self.current_buf_size < self.buffer_len:
            idx = self.current_buf_size
        else:
            idx = np.random.randint(self.current_buf_size)
        self.sample_buffer['preds_probdist'][idx] = preds_probdist
        self.sample_buffer['preds'][idx] = preds
        self.sample_buffer['obs'][idx] = obs
        self.sample_buffer['goal'][idx] = goal
        self.current_buf_size += 1
        self.current_buf_size = min(self.current_buf_size, self.buffer_len)


    def store_sample_batch(self, preds, obs, goal):
        for p,o,g in zip(preds, obs, goal):
            self.store_sample(p,o,g)

    def sample_batch(self, batch_size):
        sample_idxs = np.random.randint(0, self.current_buf_size, size=batch_size)
        probdists = self.sample_buffer['preds_probdist'][sample_idxs, :]
        obs = self.sample_buffer['obs'][sample_idxs, :]
        goals = self.sample_buffer['goal'][sample_idxs, :]
        return {'preds': probdists, 'obs': obs, 'goals': goals}


