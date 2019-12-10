import autograd.numpy as np
import autograd.numpy.random as npr

from sds import rARHMM
from sds.utils import sample_env

from joblib import Parallel, delayed


def create_job(kwargs):
    # model arguments
    nb_states = kwargs.pop('nb_states')
    trans_type = kwargs.pop('trans_type')
    obs_prior = kwargs.pop('obs_prior')
    trans_prior = kwargs.pop('trans_prior')
    trans_kwargs = kwargs.pop('trans_kwargs')

    # em arguments
    obs = kwargs.pop('obs')
    act = kwargs.pop('act')
    prec = kwargs.pop('prec')
    nb_iter = kwargs.pop('nb_iter')
    obs_mstep_kwargs = kwargs.pop('obs_mstep_kwargs')
    trans_mstep_kwargs = kwargs.pop('trans_mstep_kwargs')

    train_obs, train_act, test_obs, test_act = [], [], [], []
    train_idx = npr.choice(a=len(obs), size=int(0.8 * len(obs)), replace=False)
    for i in range(len(obs)):
        if i in train_idx:
            train_obs.append(obs[i])
            train_act.append(act[i])
        else:
            test_obs.append(obs[i])
            test_act.append(act[i])

    dm_obs = train_obs[0].shape[-1]
    dm_act = train_act[0].shape[-1]

    rarhmm = rARHMM(nb_states, dm_obs, dm_act,
                    trans_type=trans_type,
                    obs_prior=obs_prior,
                    trans_prior=trans_prior,
                    trans_kwargs=trans_kwargs)
    # rarhmm.initialize(train_obs, train_act)

    # rarhmm.em(train_obs, train_act,
    #           nb_iter=nb_iter, prec=prec, verbose=True,
    #           obs_mstep_kwargs=obs_mstep_kwargs,
    #           trans_mstep_kwargs=trans_mstep_kwargs)

    rarhmm.earlystop_em(train_obs, train_act,
                        nb_iter=nb_iter, prec=prec, verbose=True,
                        obs_mstep_kwargs=obs_mstep_kwargs,
                        trans_mstep_kwargs=trans_mstep_kwargs,
                        test_obs=test_obs, test_act=test_act)

    nb_train = np.vstack(train_obs).shape[0]
    nb_all = np.vstack(obs).shape[0]

    train_ll = rarhmm.log_norm(train_obs, train_act)
    all_ll = rarhmm.log_norm(obs, act)

    score = (all_ll - train_ll) / (nb_all - nb_train)

    return rarhmm, all_ll, score


def parallel_em(nb_jobs=50, **kwargs):
    kwargs_list = [kwargs for _ in range(nb_jobs)]
    results = Parallel(n_jobs=nb_jobs, verbose=10, backend='loky')(map(delayed(create_job), kwargs_list))
    rarhmms, lls, scores = list(map(list, zip(*results)))
    return rarhmms, lls, scores


if __name__ == "__main__":

    import matplotlib.pyplot as plt

    from hips.plotting.colormaps import gradient_cmap
    import seaborn as sns

    sns.set_style("white")
    sns.set_context("talk")

    color_names = ["windows blue", "red", "amber",
                   "faded green", "dusty purple", "orange"]

    colors = sns.xkcd_palette(color_names)
    cmap = gradient_cmap(colors)

    import os
    import torch

    import gym
    import rl

    env = gym.make('Pendulum-RL-v0')
    env._max_episode_steps = 5000
    env.unwrapped._dt = 0.01
    env.unwrapped._sigma = 1e-8

    nb_rollouts, nb_steps = 100, 250
    dm_obs = env.observation_space.shape[0]
    dm_act = env.action_space.shape[0]

    obs, act = sample_env(env, nb_rollouts, nb_steps)

    # fig, ax = plt.subplots(nrows=1, ncols=dm_obs + dm_act, figsize=(12, 4))
    # for _obs, _act in zip(obs, act):
    #     for k, col in enumerate(ax[:-1]):
    #         col.plot(_obs[:, k])
    #     ax[-1].plot(_act)
    # # plt.show()

    nb_states = 5

    obs_prior = {'mu0': 0., 'sigma0': 1e16, 'nu0': dm_obs + 2, 'psi0': 1e-2}
    trans_prior = {'l2_penalty': 1e-16, 'alpha': 1, 'kappa': 5}

    obs_mstep_kwargs = {'use_prior': False}

    trans_type = 'neural'
    trans_kwargs = {'hidden_layer_sizes': (25,),
                    'norm': {'mean': np.array([0., 0., 0.]),
                             'std': np.array([np.pi, 8., 2.5])}}
    trans_mstep_kwargs = {'nb_iter': 10, 'batch_size': 1024, 'lr': 1e-3}

    # trans_type = 'poly'
    # trans_kwargs = {'degree': 1,
    #                 'norm': {'mean': np.array([0., 0., 0.]),
    #                          'std': np.array([np.pi, 8., 2.5])}}
    # trans_mstep_kwargs = {'nb_iter': 100, 'batch_size': 1024, 'lr': 1e-3}

    models, lls, scores = parallel_em(nb_jobs=10,
                                      nb_states=nb_states, obs=obs, act=act,
                                      trans_type=trans_type,
                                      obs_prior=obs_prior,
                                      trans_prior=trans_prior,
                                      trans_kwargs=trans_kwargs,
                                      obs_mstep_kwargs=obs_mstep_kwargs,
                                      trans_mstep_kwargs=trans_mstep_kwargs,
                                      nb_iter=100, prec=1.)
    rarhmm = models[np.argmax(scores)]

    print("rarhmm, stochastic, " + rarhmm.trans_type)
    print(np.c_[lls, scores])

    plt.figure(figsize=(8, 8))
    idx = npr.choice(nb_rollouts)
    _, state = rarhmm.viterbi(obs, act)
    _seq = npr.choice(len(obs))

    plt.subplot(211)
    plt.plot(obs[_seq])
    plt.xlim(0, len(obs[_seq]))

    plt.subplot(212)
    plt.imshow(state[_seq][None, :], aspect="auto", cmap=cmap, vmin=0, vmax=len(colors) - 1)
    plt.xlim(0, len(obs[_seq]))
    plt.ylabel("$z_{\\mathrm{inferred}}$")
    plt.yticks([])

    # torch.save(rarhmm, open(rarhmm.trans_type + "_rarhmm_pendulum_polar.pkl", "wb"))
    # torch.save(rarhmm, open(rarhmm.trans_type + "_rarhmm_pendulum_cart.pkl", "wb"))
