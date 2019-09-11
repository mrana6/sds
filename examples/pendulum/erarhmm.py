import autograd.numpy as np
import autograd.numpy.random as npr

from sds import erARHMM
from sds.utils import sample_env


if __name__ == "__main__":

    np.random.seed(1337)

    import matplotlib.pyplot as plt

    from hips.plotting.colormaps import gradient_cmap
    import seaborn as sns

    sns.set_style("white")
    sns.set_context("talk")

    color_names = ["windows blue", "red", "amber",
                   "faded green", "dusty purple", "orange"]

    colors = sns.xkcd_palette(color_names)
    cmap = gradient_cmap(colors)

    import pickle
    import gym
    import rl

    env = gym.make('Pendulum-RL-v0')
    env._max_episode_steps = 5000
    env.seed(1337)

    nb_rollouts, nb_steps = 25, 200
    dm_obs = env.observation_space.shape[0]
    dm_act = env.action_space.shape[0]

    obs, act = sample_env(env, nb_rollouts, nb_steps)

    nb_states = 5
    erarhmm = erARHMM(nb_states, dm_obs, dm_act,
                      type='neural-recurrent', learn_ctl=True)
    erarhmm.initialize(obs, act)
    lls = erarhmm.em(obs, act, nb_iter=100, prec=0., verbose=True)

    plt.figure(figsize=(5, 5))
    plt.plot(lls)
    plt.show()

    plt.figure(figsize=(8, 8))
    _idx = npr.choice(nb_rollouts)
    _, _sample_obs, _sample_act = erarhmm.sample([act[_idx]], horizon=[100])

    plt.subplot(211)
    plt.plot(_sample_obs[0])
    plt.subplot(212)
    plt.plot(_sample_act[0])
    plt.show()
