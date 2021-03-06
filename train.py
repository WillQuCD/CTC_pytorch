#!/usr/bin/python
#encoding=utf-8

#train process for the model

from data_prepare.data_loader import myDataset
from data_prepare.data_loader import myDataLoader, myCNNDataLoader
from model import *
from ctcDecoder import Decoder
from warpctc_pytorch import CTCLoss
import torch
import torch.nn as nn
from torch.autograd import Variable
import time 
import numpy as np


def train(model, train_loader, loss_fn, optimizer, print_every=10):
    model.train()
    
    total_loss = 0
    print_loss = 0
    i = 0
    for data in train_loader:
        inputs, targets, input_sizes, input_sizes_list, target_sizes = data
        batch_size = inputs.size(0)
        if model.name == 'CTC_RNN':
            inputs = inputs.transpose(0,1)
        inputs = Variable(inputs, requires_grad=False)
        targets = Variable(targets, requires_grad=False)
        input_sizes = Variable(input_sizes, requires_grad=False)
        target_sizes = Variable(target_sizes, requires_grad=False)

        if USE_CUDA:
            inputs = inputs.cuda()
        
        if model.name == 'CTC_RNN':
            #pack padded input sequence
            inputs = nn.utils.rnn.pack_padded_sequence(inputs, input_sizes_list)

        out = model(inputs)

        loss = loss_fn(out, targets, input_sizes, target_sizes)
        loss /= batch_size
        print_loss += loss.data[0]

        if (i + 1) % print_every == 0:
            print('batch = %d, loss = %.4f' % (i+1, print_loss / print_every))
            logger.debug('batch = %d, loss = %.4f' % (i+1, print_loss / print_every))
            print_loss = 0
        
        total_loss += loss.data[0]
        optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm(model.parameters(), 400)                #防止梯度爆炸或者梯度消失，限制参数范围       
        optimizer.step()
        i += 1
    average_loss = total_loss / i
    print("Epoch done, average loss: %.4f" % average_loss)
    logger.info("Epoch done, average loss: %.4f" % average_loss)
    return average_loss

def dev(model, dev_loader, decoder):
    model.eval()
    total_cer = 0
    total_tokens = 0

    for data in dev_loader:
        inputs, targets, input_sizes, input_sizes_list, target_sizes =data
        batch_size = inputs.size(1)
        if model.name == 'CTC_RNN':
            inputs = inputs.transpose(0, 1)
        
        inputs = Variable(inputs, volatile=True, requires_grad=False)
        if USE_CUDA:
            inputs = inputs.cuda()
        
        if model.name == 'CTC_RNN':
            inputs = nn.utils.rnn.pack_padded_sequence(inputs, input_sizes_list)
        probs = model(inputs)
        
        probs = probs.data.cpu()
        if decoder.space_idx == -1:
            total_cer += decoder.phone_word_error(probs, input_sizes_list, targets, target_sizes)[1]
        else:
            total_cer += decoder.phone_word_error(probs, input_sizes_list, targets, target_sizes)[0]
        total_tokens += sum(target_sizes)
    acc = 1 - float(total_cer) / total_tokens
    return acc*100

def init_logger(log_file):
    import logging
    from logging.handlers import RotatingFileHandler

    logger = logging.getLogger()
    hdl = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=10)
    formatter=logging.Formatter('%(asctime)s %(filename)s[line:%(lineno)d] %(levelname)s %(message)s')
    hdl.setFormatter(formatter)
    logger.addHandler(hdl)
    logger.setLevel(logging.DEBUG)
    return logger

def main():
    global logger
    log_file = './log/train.log'
    logger = init_logger(log_file)
    
    from visdom import Visdom
    viz = Visdom()
    opts = [dict(title="Timit Spectrum_CNN"+" Loss", ylabel = 'Loss', xlabel = 'Epoch'),
            dict(title="Timit Spectrum_CNN"+" CER on Train", ylabel = 'CER', xlabel = 'Epoch'),
            dict(title='Timit Spectrum_CNN'+' CER on DEV', ylabel = 'DEV CER', xlabel = 'Epoch')]
    viz_window = [None, None, None]
    
    init_lr = 0.001
    num_epoches = 30
    least_train_epoch = 5
    end_adjust_acc = 0.5
    decay = 0.5
    count = 0
    learning_rate = init_lr
    batch_size = 8
    weight_decay = 0.005
    model_type = 'CNN_LSTM_CTC'
    
    params = { 'num_epoches':num_epoches, 'least_train_epoch':least_train_epoch, 'end_adjust_acc':end_adjust_acc,
            'decay':decay, 'learning_rate':init_lr, 'weight_decay':weight_decay, 'batch_size':batch_size }
    
    acc_best = -100
    adjust_rate_flag = False
    stop_train = False

    train_dataset = myDataset(data_set='train', feature_type="spectrum", out_type='phone', n_feats=201)
    dev_dataset = myDataset(data_set="dev", feature_type="spectrum", out_type='phone', n_feats=201)
    
    decoder = Decoder(dev_dataset.int2phone, space_idx=-1, blank_index=0)
    
    rnn_input_size = train_dataset.n_feats
    
    if model_type == 'CNN_LSTM_CTC':
        model = CNN_LSTM_CTC(rnn_input_size=rnn_input_size, rnn_hidden_size=256, rnn_layers=4, 
                    rnn_type=nn.LSTM, bidirectional=True, batch_norm=True, 
                    num_class=48, drop_out=0)
        train_loader = myCNNDataLoader(train_dataset, batch_size=batch_size, shuffle=True,
                        num_workers=4, pin_memory=False)
        dev_loader = myCNNDataLoader(dev_dataset, batch_size=batch_size, shuffle=False,
                        num_workers=4, pin_memory=False)
    else:
        model = CTC_RNN(rnn_input_size=rnn_input_size, rnn_hidden_size=256, rnn_layers=4, 
                        rnn_type=nn.LSTM, bidirectional=True, batch_norm=True, 
                        num_class=48, drop_out=0)
        train_loader = myDataLoader(train_dataset, batch_size=batch_size, shuffle=True,
                        num_workers=4, pin_memory=False)
        dev_loader = myDataLoader(dev_dataset, batch_size=batch_size, shuffle=False,
                        num_workers=4, pin_memory=False)

    if USE_CUDA:
        model = model.cuda()
    
    loss_fn = CTCLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=init_lr, weight_decay=weight_decay)
    
    adjust_time = 0
    start_time = time.time()
    loss_results = []
    training_cer_results = []
    dev_cer_results = []
    
    while not stop_train:
        if count >= num_epoches:
            break
        count += 1
        
        if adjust_rate_flag:
            learning_rate *= decay
            for param in optimizer.param_groups:
                param['lr'] *= decay
        
        print("Start training epoch: %d, learning_rate: %.5f" % (count, learning_rate))
        logger.info("Start training epoch: %d, learning_rate: %.5f" % (count, learning_rate))
        
        loss = train(model, train_loader, loss_fn, optimizer, print_every=20)
        loss_results.append(loss)
        cer = dev(model, train_loader, decoder)
        print("cer on training set is %.4f" % cer)
        logger.info("cer on training set is %.4f" % cer)
        training_cer_results.append(cer)
        acc = dev(model, dev_loader, decoder)
        dev_cer_results.append(acc)
        
        model_path_accept = './log/epoch'+str(count)+'_lr'+str(learning_rate)+'_cv'+str(acc)+'.pkl'
        #model_path_reject = './log/epoch'+str(count)+'_lr'+str(learning_rate)+'_cv'+str(acc)+'_rejected.pkl'
        
        if adjust_time == 8:
            stop_train = True
        
        ##10轮迭代之后，开始调整学习率
        if count >= least_train_epoch:
            if acc > (acc_best + end_adjust_acc):            
                model_state = model.state_dict()
                op_state = optimizer.state_dict()
                adjust_rate_flag = False
                acc_best = acc
                #torch.save(model_state, model_path_accept)
            elif (acc > acc_best):
                model_state = model.state_dict()
                op_state = optimizer.state_dict()
                adjust_rate_flag = True
                adjust_time += 1
                acc_best = acc
                #torch.save(model_state, model_path_accept)
            elif (acc <= acc_best):
                adjust_rate_flag = True
                adjust_time += 1
                #torch.save(model.state_dict(), model_path_reject)
                model.load_state_dict(model_state)
                optimizer.load_state_dict(op_state)
        
        time_used = (time.time() - start_time) / 60
        print("epoch %d done, cv acc is: %.4f, time_used: %.4f minutes" % (count, acc, time_used))
        logger.info("epoch %d done, cv acc is: %.4f, time_used: %.4f minutes" % (count, acc, time_used))
        x_axis = range(count)
        y_axis = [loss_results[0:count], training_cer_results[0:count], dev_cer_results[0:count]]
        for x in range(len(viz_window)):
            if viz_window[x] is None:
                viz_window[x] = viz.line(X = np.array(x_axis), Y = np.array(y_axis[x]), opts = opts[x],)
            else:
                viz.line(X = np.array(x_axis), Y = np.array(y_axis[x]), win = viz_window[x], update = 'replace',)

    print("End training, best cv acc is: %.4f" % acc_best)
    logger.info("End training, best cv acc is: %.4f" % acc_best)
    best_path = './log/best_model'+'_cv'+str(acc_best)+'.pkl'
    params['epoch']=count
    params['feature_type'] = train_dataset.feature_type
    params['n_feats'] = train_dataset.n_feats
    params['out_type'] = train_dataset.out_type
    torch.save(CTC_RNN.save_package(model, optimizer=optimizer, epoch=params, loss_results=loss_results, training_cer_results=training_cer_results, dev_cer_results=dev_cer_results), best_path)

if __name__ == '__main__':
    main()
