#------------------------------------------------------------------------
# Deformable DETR
# Copyright (c) 2020 SenseTime. All Rights Reserved.
# Licensed under the Apache License, Version 2.0 [see LICENSE for details]
# ------------------------------------------------------------------------
# Modified from DETR (https://github.com/facebookresearch/detr)
# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
# ------------------------------------------------------------------------
import argparse
import datetime
import json
import random
import time
import pickle
from pathlib import Path
import os
import numpy as np
import torch
from torch.utils.data import DataLoader
import datasets
import util.misc as utils
import datasets.samplers as samplers
import torch.distributed as dist
from Custom_Dataset import *
from custom_utils import *
from custom_prints import *
from custom_buffer_manager import *
from custom_training import rehearsal_training

from datasets import build_dataset, get_coco_api_from_dataset
from engine import evaluate, train_one_epoch
from main_component import TrainingPipeline
# from omegaconf import DictConfig
# import hydra

from configs.arguments import get_args_parser, deform_detr_parser, dn_detr_parser

# @hydra.main(version_base=None, config_path="conf", config_name = "config")
def main(args):
    # Initializing
    pipeline = TrainingPipeline(args)
    args = pipeline.args 

    # Constructing only the replay buffer
    if args.Construct_Replay :
        pipeline.construct_replay_buffer()
        return

    # Evaluation mode
    if args.eval:
        pipeline.evaluation_only_mode()
        return
    
    # No incremental learning process
    if pipeline.tasks == 1 :
        pipeline.only_one_task_training()
        return
        
    print("Start training")
    start_time = time.time()
    # Training loop over tasks ( for incremental learning )
    class_len = len(pipeline.Divided_Classes[0])
    for task_idx in range(pipeline.start_task, pipeline.tasks):
        # Check whether it's the first or last task
        first_training = (task_idx == 0)
        if not first_training and args.Branch_Incremental:
            class_len += len(pipeline.Divided_Classes[task_idx])
            pipeline.make_branch(task_idx, class_len, args)
        # print(f'Out features : {pipeline.model.class_embed[0].out_features}')

        last_task = (task_idx+1 == pipeline.tasks)

        # Generate new dataset
        dataset_train, data_loader_train, sampler_train, list_CC = Incre_Dataset(task_idx, args, pipeline.Divided_Classes)

        # Ready for replay training strategy 
        if first_training is False and args.Rehearsal is True:
            if args.verbose :
                check_components(pipeline.rehearsal_classes, args.verbose)

            replay_dataset = copy.deepcopy(pipeline.rehearsal_classes)

            # Combine dataset for original and AugReplay(Circular)
            original_dataset, original_loader, original_sampler = CombineDataset(
                args, replay_dataset, dataset_train, args.num_workers, args.batch_size, old_classes=pipeline.load_replay, MixReplay="Original")

            AugRplay_dataset, AugRplay_loader, AugRplay_sampler = CombineDataset(
                args, replay_dataset, dataset_train, args.num_workers, args.batch_size, old_classes=pipeline.load_replay, MixReplay="AugReplay") 

            # Set a certain configuration
            dataset_train, data_loader_train, sampler_train = dataset_configuration(
                args, original_dataset, original_loader, original_sampler, AugRplay_dataset, AugRplay_loader, AugRplay_sampler)

            # Task change for learning rate scheduler
            pipeline.lr_scheduler.task_change()
            
        # Incremental training for each epoch
        pipeline.incremental_train_epoch(task_idx=task_idx, last_task=last_task, dataset_train=dataset_train,
                                        data_loader_train=data_loader_train, sampler_train=sampler_train,
                                        list_CC=list_CC)
            
    # Calculate and print the total time taken for training
    total_time = time.time() - start_time
    total_time_str = str(datetime.timedelta(seconds=int(total_time)))
    print("Training completed in: ", total_time_str)

    
if __name__ == '__main__':
    parser = argparse.ArgumentParser('Training and evaluation script', parents=[get_args_parser()])
    parent_args = parser.parse_known_args()[0]

    # set parser
    if parent_args.model_name == 'dn_detr':
        parser = dn_detr_parser(parser)
        args = parser.parse_args()
    elif parent_args.model_name == 'deform_detr':
        parser = deform_detr_parser(parser)
        args = parser.parse_args()
    else:
        msg = 'Unsupported model name!'
        raise Exception(msg)

    if args.output_dir:
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    main(args)
