#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Jun  4 12:23:22 2019

@author: cyril
"""

import mkl
mkl.set_num_threads(64)
import os
import numpy as np
import pickle
from bot_LSTMBot import LSTMBot
import random
import torch
from sys import getsizeof
from collections import OrderedDict
from operator import add


def select_next_gen_bots(log_dir, simul_id, gen_id, all_earnings, BB, nb_bots, gen_flat_params, nb_gens= 250, network='first', nb_opps=4, normalize=True, verbose=True):
    mkl.set_num_threads(64)
    #old_gen_dir = log_dir+'/simul_'+str(simul_id)+'/gen_'+str(gen_id)
    #creating new generation directory
    lstm_ref = LSTMBot(None, network=network)

    ANEs = compute_ANE(all_earnings=all_earnings, BB=BB, nb_bots=nb_bots, nb_opps=nb_opps, normalize=normalize)
    ord_bot_ids = [el+1 for el in sorted(range(len(ANEs)), key=lambda i:ANEs[i], reverse=True)]

    #SELECTING SURVIVORS
    surv_perc = 0.3
    surv_bot_ids = ord_bot_ids[:int(surv_perc*nb_bots)]
    surv_bots_flat = []
    for bot_id in surv_bot_ids:
        surv_bot_flat = gen_flat_params[bot_id-1]
        surv_bots_flat.append(surv_bot_flat)
    surv_ANEs = [ANEs[i-1] for i in surv_bot_ids]

    ## SELECTING ELITE BOTS
    elite_bot_ids = [id_ for id_ in surv_bot_ids if (ANEs[id_-1]) > sum(surv_ANEs)/float(len(surv_ANEs))]#[:int(len(surv_bot_ids)/2)]
    if verbose:
        print('Survivors\' ANEs: ' +str(surv_ANEs))
        print('Avg surv ANEs: ' + str(sum(surv_ANEs)/float(len(surv_ANEs))))

    if len(elite_bot_ids) == 0 or len(elite_bot_ids)==len(surv_bot_ids):
        elite_bot_ids = [surv_bot_ids[i] for i in range(int(len(surv_bot_ids)))]
        if verbose: print('[Warning] There were no elite (all equal), picking all survivors as elite')


    ## Verify that no opponent is not ignored (unbeaten by elites)
    elite_earnings = np.array([list(all_earnings[elite_bot_ids[i]-1].values()) for i in range(len(elite_bot_ids))])
    if any(elite_earnings[0]<=0): #one opponent bot is not being beaten
        balanced = False
        for i in range(1, len(elite_earnings)):
            if all((elite_earnings[0] + elite_earnings[i]) >0):
                balanced = True
                break
        if balanced==False:
            if verbose: print('Elites are sligthly unbalanced vs opponents, attempting correction')
            for bot_id in ord_bot_ids[1:]:
                if all((elite_earnings[0] + np.array(list(all_earnings[bot_id-1].values()))) >0):
                    if verbose: print('Found a strong bot to get balanced elites, it has following earnings: '+str((all_earnings[bot_id-1])))
                    elite_bot_ids = elite_bot_ids + [bot_id]
                    balanced = True
                    break
        if balanced==False:
            if verbose: print('Elites remain slightly unbalanced')
            if all(np.max(elite_earnings, axis=0)>0):
                balanced = True
            else:
                if verbose: print('Elites are very unbalanced vs opponents, attempting correction')
        if balanced==False:
            lost_opp_ids = elite_earnings[0]<=0
            for k in range(sum(lost_opp_ids)):
                for bot_id in ord_bot_ids[1:]:
                    if np.array(list(all_earnings[bot_id-1].values()))[lost_opp_ids][k] >0:
                        if verbose: print('Found a weak bot to get more balanced elites, it has following earnings: '+str((all_earnings[bot_id-1])))
                        elite_bot_ids = elite_bot_ids + [bot_id]
                        break

    if len(elite_bot_ids) ==1:
        elite_bot_ids = elite_bot_ids + [surv_bot_ids[random.randint(1,len(surv_bot_ids)-1)]]   #if there is only one elite, add other one from survivors
        if verbose: print('There was only one elite, adding a random survivor as elite')

    ##Preparing elite bots
    elite_bots_flat = []
    for bot_id in elite_bot_ids:
        elite_bots_flat.append(gen_flat_params[bot_id-1])

    ## SELECTING SECOND TIER BOTS
    sec_tier_bot_ids = [id_ for id_ in surv_bot_ids if id_ not in elite_bot_ids]
    ##Preparing elite bots
    sec_tier_bots_flat = []
    for bot_id in sec_tier_bot_ids:
        sec_tier_bots_flat.append(gen_flat_params[bot_id-1])

    if verbose: print('Nb surviving bots: ' +str(len(surv_bot_ids))+ ', nb elite bots: '+str(len(elite_bot_ids)))

    nb_new_crossover = nb_bots- len(surv_bot_ids)
    cross_bots_flat = crossover_bots(parent_bots_flat = elite_bots_flat, m_sizes_ref = lstm_ref, nb_new_bots = nb_new_crossover)
    if verbose: print('Done with crossover')
    nb_new_mutant = nb_bots - len(elite_bot_ids)
    mut_rate = 0.3 - 0.25*gen_id/nb_gens #0.25 - 0.2*gen_id/nb_gens# #TODO, put values as argument, important values
    mut_strength =  0.5 - 0.4*gen_id/nb_gens #0.5 - 0.4*gen_id/nb_gens #
    mutant_bots_flat = mutate_bots(orig_bots_flat = sec_tier_bots_flat+cross_bots_flat, nb_new_bots = nb_new_mutant,
                              mut_rate=mut_rate , mut_strength=mut_strength)
    if verbose: print('Done with mutation')
    new_gen_bots = elite_bots_flat+mutant_bots_flat

    return new_gen_bots

def compute_ANE(all_earnings, BB, nb_bots=50, load = False, gen_dir = None, nb_opps = 4, normalize=True):
    if load:
        all_earnings = [0,]*nb_bots
        for bot_id in range (1,nb_bots+1):
            with open(gen_dir+'/bots/'+str(bot_id)+'/earnings.pkl', 'rb') as f:
                all_earnings[bot_id-1] = pickle.load(f)

    earnings_arr = np.array([list(earning.values()) for earning in all_earnings])

    if normalize==True:
        #set all values to positive
       # earnings_arr = [list(earning) for earning in earnings_arr]
        n_j_pos = np.max([0.1*np.ones(nb_opps),np.max(earnings_arr,axis=0)], axis=0)
        n_j_neg = np.max([0.1*np.ones(nb_opps),np.abs(np.min(earnings_arr,axis=0))], axis=0)
        if verbose:
            print('ANEs positive normalization factors: ' +str(n_j_pos))
            print('ANEs negative normalization factors: ' +str(n_j_neg))
        #alternative approach

        #use average earnings
        #n_j = np.max([np.sqrt(BB*np.ones(nb_opps)),np.average(earnings_arr,axis=0)], axis=0)

        ANEs = np.sum(np.where(earnings_arr>0, earnings_arr/n_j_pos, earnings_arr/n_j_neg), axis = 1)/nb_opps
    else:
        ANEs = np.sum(earnings_arr, axis = 1)/nb_opps
    return ANEs

def crossover_bots(parent_bots_flat, m_sizes_ref, nb_new_bots):
    cross_bots = []
    for i in range(nb_new_bots):
        #random approach, parents are selected randomly
        while(True):
            first_parent_id = random.randint(0,len(parent_bots_flat)-1)
            second_parent_id = random.randint(0,len(parent_bots_flat)-1)
            if(first_parent_id != second_parent_id):
                break
        first_parent = parent_bots_flat[first_parent_id]
        second_parent = parent_bots_flat[second_parent_id]

        #taking by layer
        dict_sizes=get_dict_sizes(m_sizes_ref.full_dict)
        i_start=0
        child_flat_params = []
        for layer in sorted(dict_sizes.keys()):
            if layer == 'lin_dec_1.weight':  #special case for very large dense layer
                for i in range(int(dict_sizes[layer]['numel']/200)): # splitting by groups of 200
                    if random.random()<0.5:
                        child_flat_params= child_flat_params+list(first_parent[i_start:i_start+200])
                    else:
                        child_flat_params = child_flat_params+list(second_parent[i_start:i_start+200])
                    i_start+=200
            else:
                if random.random()<0.5:
                    child_flat_params= child_flat_params+list(first_parent[i_start:i_start+dict_sizes[layer]['numel']])
                else:
                    child_flat_params = child_flat_params+list(second_parent[i_start:i_start+dict_sizes[layer]['numel']])
                i_start+=dict_sizes[layer]['numel']


        cross_bots.append(torch.Tensor(child_flat_params))
    return cross_bots

def mutate_bots(orig_bots_flat, mut_rate, mut_strength, nb_new_bots):
    mutant_bots=[]
    for i in range(nb_new_bots):
        orig_bot = orig_bots_flat[i%len(orig_bots_flat)]
        mutant_flat_params = torch.Tensor([orig_gene.float() if random.random()>mut_rate else  orig_gene.float() + random.gauss(mu=0, sigma=mut_strength) for orig_gene in orig_bot])
        mutant_bots.append(mutant_flat_params)
    return mutant_bots

def get_best_ANE_earnings(all_earnings, BB=100, nb_bots = 50, nb_opps=4, normalize=True):
    ANEs = compute_ANE(all_earnings=all_earnings, BB=BB, nb_bots=nb_bots, nb_opps=nb_opps, normalize=normalize)
    best_bot_id = [el for el in sorted(range(len(ANEs)), key=lambda i:ANEs[i], reverse=True)][0]
    return all_earnings[best_bot_id]
