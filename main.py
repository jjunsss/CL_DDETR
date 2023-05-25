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
from models import build_model


def get_args_parser():
    parser = argparse.ArgumentParser('Deformable DETR Detector', add_help=False)
    parser.add_argument('--lr', default=2e-4, type=float)
    parser.add_argument('--lr_backbone_names', default=["backbone.0"], type=str, nargs='+')
    parser.add_argument('--lr_backbone', default=2e-5, type=float)
    parser.add_argument('--lr_linear_proj_names', default=['reference_points', 'sampling_offsets'], type=str, nargs='+')
    parser.add_argument('--lr_linear_proj_mult', default=0.1, type=float)
    parser.add_argument('--batch_size', default=4, type=int)
    parser.add_argument('--weight_decay', default=1e-4, type=float)
    parser.add_argument('--epochs', default=600, type=int)
    parser.add_argument('--lr_drop', default=10, type=int)
    parser.add_argument('--lr_drop_epochs', default=None, type=int, nargs='+')
    #TODO : clip max grading usually set value 1 or 5 but this therory used to value 0.1 originally
    parser.add_argument('--clip_max_norm', default=0.1, type=float,
                        help='gradient clipping max norm')


    parser.add_argument('--sgd', action='store_true')

    # Variants of Deformable DETR
    parser.add_argument('--with_box_refine', default=True, action='store_true')
    parser.add_argument('--two_stage', default=False, action='store_true')

    # Model parameters
    parser.add_argument('--frozen_weights', type=str, default=None,
                        help="Path to the pretrained model. If set, only the mask head will be trained")

    # * Backbone
    parser.add_argument('--backbone', default='resnet50', type=str,
                        help="Name of the convolutional backbone to use")
    parser.add_argument('--dilation', action='store_true',
                        help="If true, we replace stride with dilation in the last convolutional block (DC5)")
    parser.add_argument('--position_embedding', default='sine', type=str, choices=('sine', 'learned'),
                        help="Type of positional embedding to use on top of the image features")
    parser.add_argument('--position_embedding_scale', default=2 * np.pi, type=float,
                        help="position / size * scale")
    parser.add_argument('--num_feature_levels', default=4, type=int, help='number of feature levels')

    # * Transformer
    parser.add_argument('--enc_layers', default=6, type=int,
                        help="Number of encoding layers in the transformer")
    parser.add_argument('--dec_layers', default=6, type=int,
                        help="Number of decoding layers in the transformer")
    parser.add_argument('--dim_feedforward', default=1024, type=int,
                        help="Intermediate size of the feedforward layers in the transformer blocks")
    parser.add_argument('--hidden_dim', default=256, type=int,
                        help="Size of the embeddings (dimension of the transformer)")
    parser.add_argument('--dropout', default=0.1, type=float,
                        help="Dropout applied in the transformer")
    parser.add_argument('--nheads', default=8, type=int,
                        help="Number of attention heads inside the transformer's attentions")
    parser.add_argument('--num_queries', default=300, type=int,
                        help="Number of query slots")
    parser.add_argument('--dec_n_points', default=4, type=int)
    parser.add_argument('--enc_n_points', default=4, type=int)

    # * Segmentation
    parser.add_argument('--masks', action='store_true',
                        help="Train segmentation head if the flag is provided")

    # Loss
    parser.add_argument('--no_aux_loss', dest='aux_loss', action='store_false',
                        help="Disables auxiliary decoding losses (loss at each layer)")

    # * Matcher
    parser.add_argument('--set_cost_class', default=3, type=float,
                        help="Class coefficient in the matching cost")
    parser.add_argument('--set_cost_bbox', default=5, type=float,
                        help="L1 box coefficient in the matching cost")
    parser.add_argument('--set_cost_giou', default=3, type=float, # GIOU is Normalized IOU -> False일 때에도, 거리 차이에를 반영할 수 있음(기존의 IOU는 틀린 경우는 전부 0으로써 결과를 예상할 수 없었는데, GIOU는 실제 존재하는 GT BBOX와 Pred BBOX의 거리를 예측하도록 노력하게 됨.)
                        help="giou box coefficient in the matching cost")

    # * Loss coefficients
    parser.add_argument('--mask_loss_coef', default=1, type=float)
    parser.add_argument('--dice_loss_coef', default=1, type=float)
    parser.add_argument('--cls_loss_coef', default=2, type=float)
    parser.add_argument('--bbox_loss_coef', default=5, type=float)
    parser.add_argument('--giou_loss_coef', default=2, type=float)
    parser.add_argument('--focal_alpha', default=0.25, type=float)

    # dataset parameters
    parser.add_argument('--dataset_file', default='coco')
    parser.add_argument('--coco_path', default='/home/nextserver/Desktop/jjunsss/LG/LG/plustotal/', type=str)
    parser.add_argument('--file_name', default='./saved_rehearsal', type=str)
    parser.add_argument('--coco_panoptic_path', type=str)
    parser.add_argument('--remove_difficult', action='store_true')
    parser.add_argument('--output_dir', default='./TEST/', help='path where to save, empty for no saving')
    parser.add_argument('--device', default='cuda',help='device to use for training / testing')
    parser.add_argument('--seed', default=42, type=int)
    parser.add_argument('--LG', default=False, action='store_true', help="for LG Dataset process")
    
    #* CL Setting 
    parser.add_argument('--pretrained_model', default=None, help='resume from checkpoint')
    parser.add_argument('--start_epoch', default=15, type=int, metavar='N',help='start epoch')
    parser.add_argument('--start_task', default=0, type=int, metavar='N',help='start task')
    parser.add_argument('--eval', action='store_true')
    parser.add_argument('--verbose', default=False, action='store_true')
    parser.add_argument('--num_workers', default=16, type=int)
    parser.add_argument('--cache_mode', default=False, action='store_true', help='whether to cache images on memory')

    #* Continual Learning 
    parser.add_argument('--Task', default=2, type=int, help='The task is the number that divides the entire dataset, like a domain.') #if Task is 1, so then you could use it for normal training.
    parser.add_argument('--Task_Epochs', default=16, type=int, help='each Task epoch, e.g. 1 task is 5 of 10 epoch training.. ')
    parser.add_argument('--Total_Classes', default=90, type=int, help='number of classes in custom COCODataset. e.g. COCO : 80 / LG : 59')
    parser.add_argument('--Total_Classes_Names', default=False, action='store_true', help="division of classes through class names (DID, PZ, VE). This option is available for LG Dataset")
    parser.add_argument('--CL_Limited', default=0, type=int, help='Use Limited Training in CL. If you choose False, you may encounter data imbalance in training.')
    parser.add_argument('--Construct_Replay', default=False, action='store_true', help="For cunstructing replay dataset")
    

    #* Rehearsal method
    parser.add_argument('--Rehearsal', default=False, action='store_true', help="use Rehearsal strategy in diverse CL method")
    parser.add_argument('--AugReplay', default=False, action='store_true', help="use Our augreplay strategy in step 2")
    parser.add_argument('--MixReplay', default=False, action='store_true', help="1:1 Mix replay solution, First Circular Training. Second Original Training")
    parser.add_argument('--Fake_Query', default=False, action='store_true', help="retaining previous task target through predict query")
    parser.add_argument('--Distill', default=False, action='store_true', help="retaining previous task target through predict query")
    parser.add_argument('--Memory', default=25, type=int, help='memory capacity for rehearsal training')
    parser.add_argument('--Continual_Batch_size', default=2, type=int, help='continual batch training method')
    parser.add_argument('--Rehearsal_file', default='./Rehearsal_LG-CL/', type=str)
    parser.add_argument('--teacher_model', default=None, type=str)
    return parser

def main(args):
    utils.init_distributed_mode(args)
    print("git:\n  {}\n".format(utils.get_sha()))
    
    if args.frozen_weights is not None:
        assert args.masks, "Frozen training is meant for segmentation only"
    print(args)

    device = torch.device(args.device)

    # fix the seed for reproducibility
    seed = args.seed + utils.get_rank()
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)

    model, criterion, postprocessors = build_model(args)
    pre_model = copy.deepcopy(model)
    model.to(device)
    if args.pretrained_model is not None:
        model = load_model_params("main", model, args.pretrained_model)
    
    teacher_model = None
    if args.Distill:    
        teacher_model = load_model_params("teacher", pre_model, args.teacher_model)
        print(f"teacher model load complete !!!!")
    
    model_without_ddp = model
    
    #* collate_fn : 최종 출력시에 모든 배치값에 할당해주는 함수를 말함. 여기서는 Nested Tensor 호출을 의미함.
    # lr_backbone_names = ["backbone.0", "backbone.neck", "input_proj", "transformer.encoder"]
    def match_name_keywords(n, name_keywords):
        out = False
        for b in name_keywords:
            if b in n:
                out = True
                break
        return out
    

    param_dicts = [
        {
            "params":
                [p for n, p in model_without_ddp.named_parameters()
                 if not match_name_keywords(n, args.lr_backbone_names) and not match_name_keywords(n, args.lr_linear_proj_names) and p.requires_grad],
            "lr": args.lr,
        },
        {
            "params": [p for n, p in model_without_ddp.named_parameters() if match_name_keywords(n, args.lr_linear_proj_names) and p.requires_grad],
            "lr": args.lr * args.lr_linear_proj_mult,
        },
        {
            "params": [p for n, p in model_without_ddp.named_parameters() if match_name_keywords(n, args.lr_backbone_names) and p.requires_grad],
            "lr": args.lr_backbone,
        },
    ]
    if args.sgd:
        optimizer = torch.optim.SGD(param_dicts, lr=args.lr, momentum=0.9,
                                    weight_decay=args.weight_decay)
    else:
        optimizer = torch.optim.AdamW(param_dicts, lr=args.lr,
                                      weight_decay=args.weight_decay)
    lr_scheduler = ContinualStepLR(optimizer, args.lr_drop, gamma = 0.5)
    # lr_scheduler = StepLR(optimizer, args.lr_drop, gamma = 0.5)

    if args.distributed:
        model = torch.nn.parallel.DistributedDataParallel(model, device_ids=[args.gpu])
        model_without_ddp = model.module

    if args.frozen_weights is not None:
        checkpoint = torch.load(args.frozen_weights, map_location='cpu')
        model_without_ddp.detr.load_state_dict(checkpoint['model'])
    output_dir = Path(args.output_dir)
    
    print("Start training")
    start_time = time.time()
    file_name = args.file_name + "_" + str(0)

    Divided_Classes = DivideTask_for_incre(args.Task, args.Total_Classes, args.Total_Classes_Names)
    if args.Total_Classes_Names == True :
        args.Task = len(Divided_Classes)    
    start_epoch = 0
    start_task = 0

    DIR = './mAP_TEST.txt'
    if args.eval:
        expand_classes = []
        for task_idx in range(int(args.Task)):
            expand_classes.extend(Divided_Classes[task_idx])
            print(f"trained task classes: {Divided_Classes[task_idx]}\t  we check all classes {expand_classes}")
            dataset_val, data_loader_val, sampler_val, current_classes  = Incre_Dataset(task_idx, args, expand_classes, False)
            base_ds = get_coco_api_from_dataset(dataset_val)
            with open(DIR, 'a') as f:
                f.write(f"NOW TASK num : {task_idx}, checked classes : {expand_classes} \t file_name : {str(os.path.basename(args.pretrained_model))} \n")
            test_stats, coco_evaluator = evaluate(model, criterion, postprocessors,
                                            data_loader_val, base_ds, device, args.output_dir, DIR)

        return
    
    if args.start_epoch != 0:
        start_epoch = args.start_epoch
    
    if args.start_task != 0:
        start_task = args.start_task
        
    load_replay = []
    for idx in range(start_task):
        load_replay.extend(Divided_Classes[idx])
    
    #* Load for Replay
    if args.Rehearsal and (start_task >= 1):
        rehearsal_classes = load_rehearsal(args.Rehearsal_file, 0, args.Memory)
    
        if len(rehearsal_classes)  == 0:
            print(f"No rehearsal file")
            rehearsal_classes = dict()
    else:
        rehearsal_classes = dict()
    
    last_task = False
    AugReplay = False
    dataset_name = "Original"
    if args.AugReplay == True:
        dataset_name = "AugReplay"
        
    if args.Construct_Replay :
        # This is only conduction replay data in buffer
        contruct_replay_extra_epoch(args=args, Divided_Classes=Divided_Classes, model=model,
                                    criterion=criterion, device=device)
        return
    
    for task_idx in range(start_task, args.Task):
        if task_idx+1 == args.Task and not args.Construct_Replay:
            last_task = True
        print(f"old class list : {load_replay}")
        

        
        #New task dataset
        dataset_train, data_loader_train, sampler_train, list_CC = Incre_Dataset(task_idx, args, Divided_Classes) #rehearsal + New task dataset (rehearsal Dataset은 유지하도록 설정)
        
        if task_idx >= 1 and args.Rehearsal:
            if args.verbose :
                check_components("replay", rehearsal_classes, args.verbose)
            replay_dataset = copy.deepcopy(rehearsal_classes)
            original_dataset, original_loader, original_sampler = CombineDataset(args, replay_dataset, dataset_train, 
                                                                     args.num_workers, args.batch_size, old_classes=load_replay, MixReplay="Original") #rehearsal + New task dataset (rehearsal Dataset은 유지하도록 설정)
    
            AugRplay_dataset, AugRplay_loader, AugRplay_sampler = CombineDataset(args, replay_dataset, dataset_train,
                                                                     args.num_workers, args.batch_size, old_classes=load_replay, MixReplay="AugReplay") 
            dataset_train, data_loader_train, sampler_train = dataset_configuration(args, original_dataset, original_loader, original_sampler,
                                                                                    AugRplay_dataset, AugRplay_loader, AugRplay_sampler)
        if task_idx >= 1 :
            # Learning rate control in task change
            lr_scheduler.task_change()
        if isinstance(dataset_train, list):
            temp_dataset, temp_loader, temp_sampler = copy.deepcopy(dataset_train), copy.deepcopy(data_loader_train), copy.deepcopy(sampler_train)
        for epoch in range(start_epoch, args.Task_Epochs): #어차피 Task마다 훈련을 진행해야 하고, 중간점음 없을 것이므로 TASK마다 훈련이 되도록 만들어도 상관이 없음
            if args.MixReplay and args.Rehearsal and task_idx >= 1:
                dataset_index = epoch % 2 
                dataset_name = ["AugReplay", "Original"]
                dataset_train = temp_dataset[dataset_index]
                data_loader_train = temp_loader[dataset_index]
                sampler_train = temp_sampler[dataset_index]
                dataset_name = dataset_name[dataset_index]
                
            if args.distributed:
                sampler_train.set_epoch(epoch)#TODO: 추후에 epoch를 기준으로 batch sampler를 추출하는 행위 자체가 오류를 일으킬 가능성이 있음 Incremental Learning에서                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               
            print(f"task id : {task_idx}")
            print(f"each epoch id : {epoch} , Dataset length : {len(dataset_train)}, current classes :{list_CC}")
            print(f"Task is Last : {last_task}")
            print(f"args task : : {args.Task}")
            
            # Training process
            rehearsal_classes = train_one_epoch(args, last_task, epoch, model, teacher_model, criterion, 
                                                data_loader_train, optimizer, lr_scheduler,
                                                device, dataset_name, list_CC, rehearsal_classes)
            
            # set a lr scheduler.
            if args.Construct_Replay is False:
                lr_scheduler.step()

            if last_task == False and args.Rehearsal:
                print(f"replay data : {rehearsal_classes}")
                rehearsal_classes = construct_combined_rehearsal(args=args, task=task_idx, dir=args.Rehearsal_file, rehearsal=rehearsal_classes,
                                                                 epoch=epoch, limit_memory_size=args.Memory, gpu_counts=4, list_CC=list_CC)
                print(f"complete save replay's data process")
                print(f"replay dataset : {rehearsal_classes}")
                #for wandb checker
                if utils.is_main_process() and epoch + 1 == args.Task_Epochs:
                    buffer_checker(rehearsal_classes)
                dist.barrier()
                
            # Save model each epoch
            save_model_params(model_without_ddp, optimizer, lr_scheduler, args, args.output_dir, task_idx, int(args.Task), epoch)

        save_model_params(model_without_ddp, optimizer, lr_scheduler, args, args.output_dir, task_idx, int(args.Task), -1)
        load_replay.extend(Divided_Classes[task_idx])
        teacher_model = model_without_ddp #Trained Model Change in change TASK 
        teacher_model = teacher_model_freeze(teacher_model)
    total_time = time.time() - start_time
    total_time_str = str(datetime.timedelta(seconds=int(total_time)))
    print('Training time {}'.format(total_time_str))

    
if __name__ == '__main__':
    parser = argparse.ArgumentParser('Deformable DETR training and evaluation script', parents=[get_args_parser()])
    args = parser.parse_args()
    if args.output_dir:
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    main(args)
