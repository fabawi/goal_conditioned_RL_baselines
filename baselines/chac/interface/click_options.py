import click
chac_options = [
click.option('--n_test_rollouts', type=int, default=25, help='The number of testing rollouts.'),
click.option('--batch_size', type=int, default=1024, help='The number of state transitions processed during network training.'),
click.option('--n_train_batches', type=int, default=40, help='The number of batches for model training.'),
click.option('--buffer_size', type=int, default=500, help='The number of rollouts to store per in each levels buffer.'),

# HAC
click.option('--q_lr', type=float, default=0.001, help='critic learning rate'),
click.option('--q_hidden_size', type=int, default=64),
click.option('--mu_lr', type=float, default=0.001, help='actor learning rate'),
click.option('--mu_hidden_size', type=int, default=64),

click.option('--time_scales', type=str, default='27,27', help='Steps per level from lowest to highest also used to define penalties'),
click.option('--subgoal_test_perc', type=float, default=0.3, help='The percentage of subgoals to test.'),
click.option('--n_levels', type=int, default=2, help='The number hierarchies'),

# Forward model
click.option('--fw', type=int, default=0, help='Enable forward model'),
click.option('--fw_hidden_size', type=str, default='128,128,128', help='Size for each hidden layer of the forward model'),
click.option('--fw_lr', type=float, default=0.001, help='Learning rate to train the forward model'),
click.option('--eta', type=float, default=0.5, help='Reward fraction (r_e * eta + (1-eta) * r_i)'),

click.option('--verbose', type=bool, default=False),
click.option('--num_threads', type=int, default=1, help='number of threads used for intraop parallelism on CPU')
]

def click_main(func):
    for option in reversed(chac_options):
        func = option(func)
    return func

@click.command()
@click_main
def get_click_option(**kwargs):
    return kwargs