import tensorflow as tf
from baselines.mbhac.utils import layer


class Actor():

    def __init__(self, sess, env, batch_size, layer_number, n_layers,
            learning_rate=0.001, tau=0.05, hidden_size=64):

        self.sess = sess
        self.hidden_size = hidden_size

        # Determine range of actor network outputs.  This will be used to configure outer layer of neural network
        if layer_number == 0:
            self.action_space_bounds = env.action_bounds
            self.action_offset = env.action_offset
        else:
            # Determine symmetric range of subgoal space and offset
            self.action_space_bounds = env.subgoal_bounds_symmetric
            self.action_offset = env.subgoal_bounds_offset

        # Dimensions of action will depend on layer level
        if layer_number == 0:
            self.action_space_size = env.action_dim
        else:
            self.action_space_size = env.subgoal_dim

        self.actor_name = 'actor_' + str(layer_number)

        # Dimensions of goal placeholder will differ depending on layer level
        if layer_number == n_layers - 1:
            self.goal_dim = env.end_goal_dim
        else:
            self.goal_dim = env.subgoal_dim

        self.state_dim = env.state_dim
        self.learning_rate = learning_rate
        self.tau = tau

        self.batch_size = tf.placeholder(tf.float32)
        self.state_ph = tf.placeholder(tf.float32, shape=(None, self.state_dim))
        self.goal_ph = tf.placeholder(tf.float32, shape=(None, self.goal_dim))
        self.features_ph = tf.concat([self.state_ph, self.goal_ph], axis=1)

        # Create actor network
        self.infer = self.create_nn(self.features_ph)

        # Target network code "repurposed" from Patrick Emani :^)
        self.weights = [v for v in tf.trainable_variables() if self.actor_name in v.op.name]

        self.action_derivs = tf.placeholder(tf.float32, shape=(None, self.action_space_size))
        self.unnormalized_actor_gradients = tf.gradients(self.infer, self.weights, -self.action_derivs)
        self.policy_gradient = list(map(lambda x: tf.div(x, self.batch_size), self.unnormalized_actor_gradients))

        # self.policy_gradient = tf.gradients(self.infer, self.weights, -self.action_derivs)
        self.train = tf.train.AdamOptimizer(learning_rate).apply_gradients(zip(self.policy_gradient, self.weights))

    def get_action(self, state, goal):
        return self.sess.run(self.infer,
                feed_dict={
                    self.state_ph: state,
                    self.goal_ph: goal
                    })

    def update(self, state, goal, action_derivs, next_batch_size):
        weights, policy_grad, _ = self.sess.run(
                [self.weights, self.policy_gradient, self.train],
                feed_dict={
                    self.state_ph: state,
                    self.goal_ph: goal,
                    self.action_derivs: action_derivs,
                    self.batch_size: next_batch_size
                })

        return len(weights)

    def create_nn(self, features, name=None):

        if name is None:
            name = self.actor_name

        with tf.variable_scope(name + '_fc_1'):
            fc1 = layer(features, self.hidden_size)
        with tf.variable_scope(name + '_fc_2'):
            fc2 = layer(fc1, self.hidden_size)
        with tf.variable_scope(name + '_fc_3'):
            fc3 = layer(fc2, self.hidden_size)
        with tf.variable_scope(name + '_fc_4'):
            fc4 = layer(fc3, self.action_space_size, is_output=True)

        output = tf.tanh(fc4) * self.action_space_bounds + self.action_offset

        return output
