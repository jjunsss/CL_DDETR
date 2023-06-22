PUS_PER_NODE=4 ./tools/run_dist_launch.sh 4 ./configs/dn_detr.sh \
    --batch_size 3 \
    --model_name dn_detr \
    --use_dn \
    --output_dir "./results/testt/" \
    --Task_Epochs 3 \
    --Task 2 \
    --CL_Limited 0 \
    --start_epoch 0 \
    --start_task 0 \
    --verbose  \
    --Total_Classes 59 \
    --LG \
    --coco_path "../../lg/didvepz/plustotal/" \
    --Total_Classes_Names \
    --num_workers 16  \
    --limit_image 1000 \
    --least_image 30 \
    --Branch_Incremental \
    --Rehearsal \
    --Sampling_strategy icarl \
    --debug