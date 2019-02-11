import tensorflow as tf
from baselines.util import store_args, nn
from tensorflow.contrib.rnn import GRUCell, LSTMCell, MultiRNNCell
import numpy as np


class FF_Simple3:
    @store_args
    def __init__(self, inputs_tf, **kwargs):
        """The actor-critic network and related training code.

        Args:
            inputs_tf (dict of tensors): all necessary inputs for the network: the
                observation (o), the action (u) and the successive observation (o2) (o2 not required for the network)
        """
        print("Initializing model")
        self.o_tf = inputs_tf['o']
        self.u_tf = inputs_tf['u']
        self.loss_tf = inputs_tf['loss']
        self.u2_tf = inputs_tf['u2']
        #
        dimu = self.u_tf.shape[2]
        #
        hidden = 100
        layers = 3
        #
        with tf.variable_scope('AdversarialControlRNN'):
            input = tf.concat(axis=2, values=[self.o_tf, self.u_tf])
            self.output = nn(input, [hidden] * layers + [dimu])

        self.obs_loss_per_step_tf = tf.reduce_mean(tf.abs(self.output - self.o2_tf), axis=2)
        self.obs_loss_tf = tf.reduce_mean(self.obs_loss_per_step_tf)

# class State_GRU1:
#     @store_args
#     def __init__(self, inputs_tf, **kwargs):
#         """The actor-critic network and related training code.
#
#         Args:
#             inputs_tf (dict of tensors): all necessary inputs for the network: the
#                 observation (o), the action (u) and the successive observation (o2) (o2 not required for the network)
#         """
#         print("Initializing model")
#         self.o_tf = inputs_tf['o']
#         self.o2_tf = inputs_tf['o2']
#         self.u_tf = inputs_tf['u']
#         self.max_batch_size = kwargs['model_train_batch_size']
#
#         #
#         dimo = self.o_tf.shape[2]
#         #
#         size = 100
#
#         # layers = 3
#         with tf.variable_scope('AdversarialControlRNN'):
#             # create a BasicRNNCell
#             self.rnn_cell = tf.nn.rnn_cell.GRUCell(size)
#
#             # defining initial zero state
#             self.initial_state = self.rnn_cell.zero_state(self.max_batch_size, dtype=tf.float32)
#
#             input = tf.concat(axis=2, values=[self.o_tf, self.u_tf])
#
#             out, state = tf.nn.dynamic_rnn(
#                 self.rnn_cell,
#                 input,
#                 initial_state=self.initial_state,
#                 dtype=tf.float32)
#
#             self.state = state
#             self.output = tf.layers.dense(out, dimo)
#
#         self.obs_loss_per_step_tf = tf.reduce_mean(tf.abs(self.output - self.o2_tf), axis=2)
#         self.obs_loss_tf = tf.reduce_mean(self.obs_loss_per_step_tf)