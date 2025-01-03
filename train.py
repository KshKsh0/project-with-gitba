import torch
import matplotlib.pyplot as plt
# import torch.optim as optim
# from torch.optim import lr_scheduler
# import torch.utils.data as data
# from torch.autograd import Variable as V

import random
import math
# import cv2
import os
# import warnings
import numpy as np

from time import time


from model import LinkNet34, DinkNet34, DinkNet50, DinkNet101, DinkNet152, DinkNet34_less_pool
from framework import MyFrame
from loss import dice_bce_loss, bce_loss, JaccLoss
from data import ImageFolder

# import torch.nn.functional as F
# from test import TTAFrame

SEED = 0

def train():

    # fix seed
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    np.random.seed(SEED)
    random.seed(SEED)
    torch.backends.cudnn.deterministic = True

    # the network need the size to be a multiple of 32, resize is intriduced
    ORIG_SHAPE = (400, 400)
    SHAPE = (384, 384)
    NAME = 'DinkNet101_Dr.Tmam '
    BATCHSIZE_PER_CARD = 8

    train_root = 'dataset/train/'
    image_root = os.path.join(train_root, 'images')
    gt_root = os.path.join(train_root, 'groundtruth')
    image_list = np.array(sorted(
        [f for f in os.listdir(image_root) if f.endswith('.png')]))
    gt_list = np.array(sorted(
        [f for f in os.listdir(gt_root) if f.endswith('.png')]))
    # imagelist = filter(lambda : x.find('sat') != -1, os.listdir(train_root))

    # random select 20% of training data for validation
    total_data_num = image_list.shape[0]
    validation_data_num = math.ceil(total_data_num * 0.2)
    validation_idx = random.sample(range(total_data_num), validation_data_num)
    new_train_indx = list(
        set(range(total_data_num)).difference(set(validation_idx)))

    val_img_list = image_list[validation_idx].tolist()
    val_gt_list = gt_list[validation_idx].tolist()
    image_list = image_list[new_train_indx].tolist()
    gt_list = gt_list[new_train_indx].tolist()

    solver = MyFrame(DinkNet152, dice_bce_loss, 1e-4)

    if torch.cuda.is_available():
        train_batchsize = torch.cuda.device_count() * BATCHSIZE_PER_CARD
        val_batchsize = torch.cuda.device_count() * BATCHSIZE_PER_CARD
    else:
        train_batchsize = BATCHSIZE_PER_CARD
        val_batchsize = BATCHSIZE_PER_CARD

    #  data preprocessing here
    train_dataset = ImageFolder(image_list, image_root, gt_root, SHAPE)
    val_dataset = ImageFolder(val_img_list, image_root, gt_root, SHAPE)
    # print("train_dataset", train_dataset)

    data_loader = torch.utils.data.DataLoader(
        train_dataset,
        batch_size=train_batchsize,
        shuffle=True,
        num_workers=0)
    # print("data loader", data_loader)

    val_data_loader = torch.utils.data.DataLoader(
        val_dataset,
        batch_size=val_batchsize,
        shuffle=True,
        num_workers=0)

    mylog = open('logs/'+NAME+'.log', 'w')
    tic = time()
    no_optim = 0
    total_epoch = 100
    train_epoch_best_loss = 100.
    train_loss_list = []
    val_loss_list = []
    train_F1_list = []
    val_F1_list = []

    for epoch in range(1, total_epoch + 1):
        print('---------- Epoch:'+str(epoch) + ' ----------')
        data_loader_iter = iter(data_loader)
        train_epoch_loss = 0
        train_epoch_F1 = 0

        print('Train:')
        for img, mask in data_loader_iter:
            solver.set_input(img, mask)
            train_F1, train_loss = solver.optimize()

            train_epoch_loss += train_loss
            train_epoch_F1 += train_F1

        train_epoch_loss /= len(data_loader_iter)
        train_epoch_F1 /= len(data_loader_iter)

        duration_of_epoch = int(time()-tic)

        train_F1_list.append(train_F1)
        
        # append the loss list 
        train_loss_list.append(train_epoch_loss)
        
        mylog.write('********************' + '\n')
        mylog.write('--epoch:' + str(epoch) + '  --time:' + str(duration_of_epoch) + '  --train_loss:' + str(
            train_epoch_loss) + '  --train_F1:' + str(
            train_epoch_F1) + '\n')
        print('--epoch:', epoch, '  --time:', duration_of_epoch, '  --train_loss:',
              train_epoch_loss, '  --train_F1:', train_epoch_F1)

        # if epoch % 5 == 0 and os.path.exists('weights/'+NAME+'.th'):
        val_data_loader_iter = iter(val_data_loader)
        validation_epoch_loss = 0
        validation_epoch_F1 = 0
        print("Validation: ")

        for val_img, val_mask in val_data_loader_iter:
            solver.set_input(val_img, val_mask)
            val_F1, val_loss = solver.optimize(True)
            validation_epoch_loss += val_loss
            validation_epoch_F1 += val_F1
        validation_epoch_loss /= len(val_data_loader_iter)
        validation_epoch_F1 /= len(val_data_loader_iter)
        
        val_loss_list.append(validation_epoch_loss)
        val_F1_list.append(validation_epoch_F1)

        mylog.write('--epoch:' + str(epoch) +
                    '  --validation_loss:' + str(validation_epoch_loss) + 
                    '  --validation_F1:' + str(validation_epoch_F1) + '\n')
        print('--epoch:', epoch,  '  --validation_loss:',
                validation_epoch_loss, '  --validation_F1:',
                validation_epoch_F1)

        if train_epoch_loss >= train_epoch_best_loss:
            no_optim += 1
        else:
            no_optim = 0
            train_epoch_best_loss = train_epoch_loss
            solver.save('weights/'+NAME+'.th')

        if no_optim > 6:
            mylog.write('early stop at' + str(epoch)+'epoch')
            print('early stop at %d epoch' % epoch)
            break
        if no_optim > 3 and solver.old_lr>=5e-7:
            # if solver.old_lr < 5e-7:
            #     break
            # solver.load(last_save_name)
            solver.load('weights/'+NAME+'.th')
            solver.update_lr(2.0, factor=True, mylog=mylog)
            
        mylog.flush()

    mylog.write('--complete_train_loss:' + str(train_loss_list) + '\n')
    mylog.write('--complete_validation_loss:' + str(val_loss_list) + '\n')
    mylog.write('--complete_train_F1_scores:' + str(train_F1_list) + '\n')
    mylog.write('--complete_validation_F1_scores:' + str(val_F1_list) + '\n')
    print(mylog, 'Finish!')
    print('Finish!')
    mylog.close()