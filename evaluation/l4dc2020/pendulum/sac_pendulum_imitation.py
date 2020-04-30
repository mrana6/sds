import numpy as np
import numpy.random as npr

from sds import erARHMM
from sds.utils import sample_env

from joblib import Parallel, delayed
import copy

import matplotlib.pyplot as plt
from matplotlib import rc

import multiprocessing
nb_cores = multiprocessing.cpu_count()


rc('lines', **{'linewidth': 1})
rc('text', usetex=True)
rc('font', **{'family': 'serif', 'serif': ['Palatino']})


def beautify(ax):
    ax.set_frame_on(True)
    ax.minorticks_on()

    ax.grid(True)
    ax.grid(linestyle=':')

    ax.tick_params(which='both', direction='in',
                   bottom=True, labelbottom=True,
                   top=True, labeltop=False,
                   right=True, labelright=False,
                   left=True, labelleft=True)

    ax.tick_params(which='major', length=6)
    ax.tick_params(which='minor', length=3)

    ax.autoscale(tight=True)
    # ax.set_aspect('equal')

    if ax.get_legend():
        ax.legend(loc='best')

    return ax


def evaluate(env, erarhmm, nb_rollouts, nb_steps, stoch=False, mix=False):
    if stoch:
        # it doesn't make sense to mix while sampling
        assert not mix

    rollouts = []

    dm_obs = env.observation_space.shape[0]
    dm_act = env.action_space.shape[0]

    ulim = env.action_space.high
    nb_states = erarhmm.nb_states

    for n in range(nb_rollouts):
        roll = {'z': np.empty((0,), np.int64),
                'b': np.empty((0, nb_states)),  # belief
                'x': np.empty((0, dm_obs)),
                'u': np.empty((0, dm_act)),
                'r': np.empty((0, ))}

        x = env.reset()
        roll['x'] = np.vstack((roll['x'], x))

        b = erarhmm.init_state.pi
        roll['b'] = np.vstack((roll['b'], b))

        u = np.zeros((dm_act,))
        if stoch:
            z = npr.choice(nb_states, p=b)
            roll['z'] = np.hstack((roll['z'], z))

            if erarhmm.ar_ctl:
                u = erarhmm.init_control.sample(z, x)
            else:
                u = erarhmm.controls.sample(z, x)
        else:
            if mix:
                # this is just for plotting
                z = np.argmax(b)
                roll['z'] = np.hstack((roll['z'], z))

                for k in range(nb_states):
                    if erarhmm.ar_ctl:
                        u += b[k] * erarhmm.init_control.mean(k, x)
                    else:
                        u += b[k] * erarhmm.controls.mean(k, x)
            else:
                z = np.argmax(b)
                roll['z'] = np.hstack((roll['z'], z))

                for k in range(nb_states):
                    if erarhmm.ar_ctl:
                        u = erarhmm.init_control.mean(z, x)
                    else:
                        u = erarhmm.controls.mean(z, x)

        u = np.clip(u, -ulim, ulim)
        roll['u'] = np.vstack((roll['u'], u))

        for t in range(nb_steps):
            x, r, _, _ = env.step(u)
            roll['x'] = np.vstack((roll['x'], x))
            roll['r'] = np.hstack((roll['r'], r))

            # pad action
            _aux_u = np.vstack((roll['u'], np.zeros((1, dm_act))))

            b = erarhmm.filter(roll['x'], _aux_u)[0][-1]
            roll['b'] = np.vstack((roll['b'], b))

            u = np.zeros((dm_act, ))
            if stoch:
                z = npr.choice(nb_states, p=b)
                roll['z'] = np.hstack((roll['z'], z))

                if erarhmm.ar_ctl:
                    if t < erarhmm.lags:
                        u = erarhmm.init_control.sample(z, x)
                    else:
                        u = erarhmm.controls.sample(z, roll['x'][-(1 + erarhmm.lags):])
                else:
                    u = erarhmm.controls.sample(z, x)
            else:
                if mix:
                    # this is only for plotting
                    z = np.argmax(b)
                    roll['z'] = np.hstack((roll['z'], z))

                    for k in range(nb_states):
                        if erarhmm.ar_ctl:
                            if t < erarhmm.lags:
                                u += b[k] * erarhmm.init_control.mean(k, x)
                            else:
                                u += b[k] * erarhmm.controls.mean(k, roll['x'][-(1 + erarhmm.lags):])
                        else:
                            u += b[k] * erarhmm.controls.mean(k, x)
                else:
                    z = np.argmax(b)
                    roll['z'] = np.hstack((roll['z'], z))

                    if erarhmm.ar_ctl:
                        if t < erarhmm.lags:
                            u = erarhmm.init_control.mean(z, x)
                        else:
                            u = erarhmm.controls.mean(z, roll['x'][-(1 + erarhmm.lags):])
                    else:
                        u = erarhmm.controls.mean(z, x)

            u = np.clip(u, -ulim, ulim)
            roll['u'] = np.vstack((roll['u'], u))

        rollouts.append(roll)
    return rollouts


def create_job(kwargs):
    # model arguments
    nb_states = kwargs.pop('nb_states')
    trans_type = kwargs.pop('trans_type')
    ar_ctl = kwargs.pop('ar_ctl')
    lags = kwargs.pop('lags')
    obs_prior = kwargs.pop('obs_prior')
    ctl_prior = kwargs.pop('ctl_prior')
    trans_prior = kwargs.pop('trans_prior')
    init_ctl_kwargs = kwargs.pop('init_ctl_kwargs')
    ctl_kwargs = kwargs.pop('ctl_kwargs')
    trans_kwargs = kwargs.pop('trans_kwargs')

    # em arguments
    obs = kwargs.pop('obs')
    act = kwargs.pop('act')
    prec = kwargs.pop('prec')
    nb_iter = kwargs.pop('nb_iter')
    obs_mstep_kwargs = kwargs.pop('obs_mstep_kwargs')
    ctl_mstep_kwargs = kwargs.pop('ctl_mstep_kwargs')
    trans_mstep_kwargs = kwargs.pop('trans_mstep_kwargs')

    learn_dyn = kwargs.pop('learn_dyn')
    learn_ctl = kwargs.pop('learn_ctl')

    model = kwargs.pop('model')

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

    if model is None:
        erarhmm = erARHMM(nb_states, dm_obs, dm_act,
                          trans_type=trans_type,
                          ar_ctl=ar_ctl, lags=lags,
                          obs_prior=obs_prior,
                          ctl_prior=ctl_prior,
                          trans_prior=trans_prior,
                          init_ctl_kwargs=init_ctl_kwargs,
                          ctl_kwargs=ctl_kwargs,
                          trans_kwargs=trans_kwargs,
                          learn_dyn=learn_dyn,
                          learn_ctl=learn_ctl)
        erarhmm.initialize(train_obs, train_act)
    else:
        erarhmm = copy.deepcopy(model)
        erarhmm.learn_dyn = learn_dyn
        erarhmm.learn_ctl = learn_ctl
        erarhmm.controls.reset()

    erarhmm.em(train_obs, train_act,
               nb_iter=nb_iter, prec=prec,
               obs_mstep_kwargs=obs_mstep_kwargs,
               ctl_mstep_kwargs=ctl_mstep_kwargs,
               trans_mstep_kwargs=trans_mstep_kwargs)

    nb_train = np.vstack(train_obs).shape[0]
    nb_all = np.vstack(obs).shape[0]

    train_ll = erarhmm.log_norm(train_obs, train_act)
    all_ll = erarhmm.log_norm(obs, act)

    score = (all_ll - train_ll) / (nb_all - nb_train)

    return erarhmm, all_ll, score


def parallel_em(nb_jobs=50, **kwargs):
    kwargs_list = [kwargs for _ in range(nb_jobs)]
    results = Parallel(n_jobs=min(nb_jobs, nb_cores), verbose=10, backend='loky')(map(delayed(create_job), kwargs_list))
    erarhmms, lls, scores = list(map(list, zip(*results)))
    return erarhmms, lls, scores


if __name__ == "__main__":

    from hips.plotting.colormaps import gradient_cmap
    import seaborn as sns

    sns.set_style("white")
    sns.set_context("talk")

    color_names = ["windows blue", "red", "amber",
                   "faded green", "dusty purple",
                   "orange", "clay", "pink", "greyish",
                   "mint", "light cyan", "steel blue",
                   "forest green", "pastel purple",
                   "salmon", "dark brown"]

    colors = sns.xkcd_palette(color_names)
    cmap = gradient_cmap(colors)

    import os
    import random
    import torch

    import gym
    import rl

    np.set_printoptions(precision=5, suppress=True)

    random.seed(1337)
    npr.seed(1337)
    torch.manual_seed(1337)

    env = gym.make('Pendulum-RL-v1')
    env._max_episode_steps = 5000
    env.unwrapped._dt = 0.01
    env.unwrapped._sigma = 1e-8
    env.unwrapped._global = True
    env.seed(1337)

    dm_obs = env.observation_space.shape[0]
    dm_act = env.action_space.shape[0]

    from stable_baselines import SAC
    _ctl = SAC.load("./data/sac_pendulum_cart")
    sac_ctl = lambda x: _ctl.predict(x)[0]
    nb_rollouts, nb_steps = 50, 500
    obs, act = sample_env(env, nb_rollouts, nb_steps, sac_ctl, np.sqrt(1e-2))

    fig, axs = plt.subplots(nrows=1, ncols=3, figsize=(16, 6))
    fig.suptitle('Pendulum SAC Demonstrations')

    for _obs, _act in zip(obs, act):
        # angle = np.arctan2(_obs[:, 1], _obs[:, 0])
        # axs[0].plot(angle)
        axs[0].plot(_obs[:, 0])
        axs[0] = beautify(axs[0])
        axs[1].plot(_obs[:, -1])
        axs[1] = beautify(axs[1])
        axs[2].plot(_act)
        axs[2] = beautify(axs[2])

    axs[0].set_xlabel('Time Step')
    axs[1].set_xlabel('Time Step')
    axs[2].set_xlabel('Time Step')

    axs[0].set_ylabel('$\\cos(\\theta)$')
    axs[1].set_ylabel('$\\dot{\\theta}$')
    axs[2].set_ylabel('$u$')

    plt.show()

    #
    nb_states = 7

    obs_prior = {'mu0': 0., 'sigma0': 1e32, 'nu0': (dm_obs + 1) + 10, 'psi0': 1e-8 * 10}
    ctl_prior = {'mu0': 0., 'sigma0': 1e32, 'nu0': (dm_act + 1) + 10, 'psi0': 1e-2 * 10}

    init_ctl_kwargs = {'degree': 1}
    ctl_kwargs = {'degree': 3}

    ar_ctl = True
    lags = 1

    obs_mstep_kwargs = {'use_prior': True}
    ctl_mstep_kwargs = {'use_prior': True}

    trans_type = 'neural'
    trans_prior = {'l2_penalty': 1e-32, 'alpha': 1, 'kappa': 100}
    trans_kwargs = {'hidden_layer_sizes': (25,),
                    'norm': {'mean': np.array([0., 0., 0., 0.]),
                             'std': np.array([1., 1., 8., 2.5])}}
    trans_mstep_kwargs = {'nb_iter': 25, 'batch_size': 256, 'lr': 1e-3}

    models, lls, scores = parallel_em(nb_jobs=1, model=None,
                                      nb_states=nb_states,
                                      obs=obs, act=act,
                                      learn_dyn=True, learn_ctl=True,
                                      trans_type=trans_type,
                                      ar_ctl=ar_ctl, lags=lags,
                                      obs_prior=obs_prior,
                                      ctl_prior=ctl_prior,
                                      trans_prior=trans_prior,
                                      init_ctl_kwargs=init_ctl_kwargs,
                                      ctl_kwargs=ctl_kwargs,
                                      trans_kwargs=trans_kwargs,
                                      obs_mstep_kwargs=obs_mstep_kwargs,
                                      ctl_mstep_kwargs=ctl_mstep_kwargs,
                                      trans_mstep_kwargs=trans_mstep_kwargs,
                                      nb_iter=50, prec=1e-2)
    erarhmm = models[np.argmax(scores)]

    erarhmm.learn_dyn = True
    erarhmm.learn_ctl = False

    #
    state, ctl = erarhmm.filter_control(obs, act, stoch=False, mix=False)
    _seq = npr.choice(len(obs))

    fig, axs = plt.subplots(nrows=4, ncols=1, figsize=(8, 12), constrained_layout=True)
    fig.suptitle('Demonstration Action Filtering')

    angle = np.arctan2(obs[_seq][:, 1], obs[_seq][:, 0])
    axs[0].plot(angle)
    axs[0].set_ylabel('$\\theta$')
    axs[0].set_xlim(0, len(obs[_seq]))

    axs[1].plot(obs[_seq][:, -1], '-g')
    axs[1].set_ylabel("$\\dot{\\theta}$")
    axs[1].set_xlim(0, len(obs[_seq]))

    axs[2].plot(act[_seq])
    axs[2].plot(ctl[_seq])
    axs[2].legend(('Actual', 'Inferred'))
    axs[2].set_ylabel("$u$")
    axs[2].set_xlim(0, len(act[_seq]))

    axs[3].imshow(state[_seq][None, :], aspect="auto", cmap=cmap, vmin=0, vmax=len(colors) - 1)
    axs[3].set_xlim(0, len(obs[_seq]))
    axs[3].set_xlabel('Time Step')
    axs[3].set_ylabel("$z_{\\mathrm{inferred}}$")
    axs[3].set_yticks([])

    plt.show()

    #
    rollouts = evaluate(env, erarhmm, 50, 750, stoch=True, mix=False)
    _idx = np.random.choice(len(rollouts))

    fig, axs = plt.subplots(nrows=4, ncols=1, figsize=(8, 12), constrained_layout=True)
    fig.suptitle('Pendulum Hybrid Imitation: One Example')

    axs[0].plot(rollouts[_idx]['x'][:, :-1])
    axs[0].set_ylabel('$\\cos(\\theta)/\\sin(\\theta)$')
    axs[0].set_xlim(0, len(rollouts[_idx]['x']))

    axs[1].plot(rollouts[_idx]['x'][:, -1], '-g')
    axs[1].set_ylabel("$\\dot{\\theta}$")
    axs[1].set_xlim(0, len(rollouts[_idx]['x']))

    axs[2].plot(rollouts[_idx]['u'], '-r')
    axs[2].set_ylabel('$u$')
    axs[2].set_xlim(0, len(rollouts[_idx]['u']))

    axs[3].imshow(rollouts[_idx]['z'][None, :], aspect="auto", cmap=cmap, vmin=0, vmax=len(colors) - 1)
    axs[3].set_xlim(0, len(rollouts[_idx]['z']))
    axs[3].set_xlabel('Time Step')
    axs[3].set_ylabel("$z_{\\mathrm{inferred}}$")
    axs[3].set_yticks([])

    plt.show()

    fig, axs = plt.subplots(nrows=1, ncols=4, figsize=(20, 6), constrained_layout=True)
    fig.suptitle('Pendulum Hybrid Imitation: Many Seeds')

    for roll in rollouts:
        axs[0].plot(roll['x'][:, 0])
        axs[0] = beautify(axs[0])
        axs[1].plot(roll['x'][:, -1])
        axs[1] = beautify(axs[1])
        axs[2].plot(roll['u'])
        axs[2] = beautify(axs[2])
        axs[3].plot(roll['z'])
        axs[3] = beautify(axs[3])

    axs[0].set_xlabel('Time Step')
    axs[1].set_xlabel('Time Step')
    axs[2].set_xlabel('Time Step')
    axs[3].set_xlabel('Time Step')

    axs[0].set_ylabel('$\\cos(\\theta)$')
    axs[1].set_ylabel("$\\dot{\\theta}$")
    axs[2].set_ylabel('$u$')
    axs[3].set_ylabel('$z$')

    plt.show()

    fig = plt.figure(figsize=(5, 5), frameon=True)
    fig.suptitle('Pendulum Hybrid Imitation: Phase Portrait')

    ax = fig.gca()
    for roll in rollouts[:25]:
        angle = np.arctan2(roll['x'][:, 1], roll['x'][:, 0])
        ax.scatter(angle[::3], roll['x'][::3, 2], color='g', s=1.5)
    ax = beautify(ax)

    ax.set_xlabel('$\\theta$')
    ax.set_ylabel("$\\dot{\\theta}$")

    plt.show()

    # from tikzplotlib import save
    # save("sac_pendulum_imitation_phase.tex")

    # success rate
    success = 0.
    for roll in rollouts:
        angle = np.arctan2(roll['x'][:, 1], roll['x'][:, 0])
        if np.all(np.fabs(angle[500:]) < np.deg2rad(15)):
            success += 1.