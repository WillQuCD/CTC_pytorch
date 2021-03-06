#!/usr/bin/python
#encoding=utf-8

import os
import h5py
import numpy as np
import torch
import sys
from torch.utils.data import DataLoader
from torch.utils.data import Dataset
import torchaudio
import scipy.signal
import librosa
import math

windows = {'hamming':scipy.signal.hamming, 'hann':scipy.signal.hann, 'blackman':scipy.signal.blackman,
            'bartlett':scipy.signal.bartlett}
audio_conf = {"sample_rate":16000, 'window_size':0.025, 'window_stride':0.01, 'window': 'hamming'}

def load_audio(path):
    sound, _ = torchaudio.load(path)
    sound = sound.numpy()
    if len(sound.shape) > 1:
        if sound.shape[1] == 1:
            sound = sound.squeeze()
        else:
            sound - sound.mean(axis=1)
    return sound

data_dir = '/home/fan/pytorch/CTC_pytorch/data_prepare/timit'

#Override the class of Dataset
#Define my own dataset over timit used the feature extracted by kaldi
class myDataset(Dataset):
    def __init__(self, data_set='train', feature_type='spectrum', out_type='phone', n_feats=39, normalize=True):
        self.data_set = data_set
        self.out_type = out_type
        self.feature_type = feature_type
        self.normalize = normalize
        h5_file = os.path.join(data_dir, feature_type+'_'+out_type+'_tmp', data_set+'.h5py')
        wav_path = os.path.join(data_dir, 'wav_path', data_set+'.wav.scp')
        mfcc_file = os.path.join(data_dir, "feature_"+feature_type, data_set+'.txt')
        label_file = os.path.join(data_dir,"label_"+out_type, data_set+'.text')
        char_file = os.path.join(data_dir, out_type+'_list.txt')
        if not os.path.exists(h5_file):
            if feature_type != 'spectrum':
                self.n_feats = n_feats
                print("Process %s data in kaldi format..." % data_set)
                self.process_txt(mfcc_file, label_file, char_file, h5_file)
            else:
                print("Extract spectrum with librosa...")
                self.n_feats = int(audio_conf['sample_rate']*audio_conf['window_size']/2+1)
                self.process_audio(wav_path, label_file, char_file, h5_file)
        else:
            if feature_type != "spectrum":
                self.n_feats = n_feats
            else:
                self.n_feats = int(audio_conf["sample_rate"]*audio_conf["window_size"]/2+1)
                #self.n_feats = n_feats
            print("Loading %s data from h5py file..." % data_set)
            self.load_h5py(h5_file)
    
    def process_txt(self, mfcc_file, label_file, char_file, h5_file):
        #read map file
        self.char_map = dict()
        self.int2phone = dict()
        f = open(char_file, 'r')
        for line in f.readlines():
            char, num = line.strip().split(' ')
            self.char_map[char] = int(num)
            self.int2phone[int(num)] = char
        f.close()
        self.int2phone[0] = '#'
        

        #read the label file
        label_dict = dict()
        f = open(label_file, 'r')
        for label in f.readlines():
            label = label.strip()
            label_list = []
            if self.out_type == 'char':
                utt = label.split('\t', 1)[0]
                label = label.split('\t', 1)[1]
                for i in range(len(label)):
                    if label[i].lower() in self.char_map:
                        label_list.append(self.char_map[label[i].lower()])
                    if label[i] == ' ':
                        label_list.append(28)
            else:
                label = label.split()
                utt = label[0]
                for i in range(1,len(label)):
                    label_list.append(self.char_map[label[i]])
            label_dict[utt] = np.array(label_list)
        f.close()
        
        #read the mfcc file
        mfcc_dict = dict()
        f = open(mfcc_file, 'r')
        for line in f.readlines():
            mfcc_frame = list()
            line = line.strip().split()
            if len(line) == 2:
                utt = line[0]
                mfcc_dict[utt] = list()
                continue
            if len(line) > 2:
                for i in range(self.n_feats):
                    mfcc_frame.append(float(line[i]))
            mfcc_dict[utt].append(mfcc_frame)
        f.close()
        
        if len(mfcc_dict) != len(label_dict):
            print("%s data: The num of wav and text are not the same!" % self.data_set)
            sys.exit(1)

        self.features_label = []
        #save the data as h5 file
        f = h5py.File(h5_file, 'w')
        f.create_dataset("phone_map_key", data=self.char_map.keys())
        f.create_dataset("phone_map_value", data = self.char_map.values())
        for utt in mfcc_dict:
            grp = f.create_group(utt)
            self.features_label.append((torch.FloatTensor(np.array(mfcc_dict[utt])), label_dict[utt].tolist()))
            grp.create_dataset('data', data=np.array(mfcc_dict[utt]))
            grp.create_dataset('label', data=label_dict[utt])
        print("Saved the %s data to h5py file" % self.data_set)
        #print(self.__getitem__(1))
            
    def process_audio(self, wav_path, label_file, char_file, h5_file):
        #read map file
        self.char_map = dict()
        self.int2phone = dict()
        f = open(char_file, 'r')
        for line in f.readlines():
            char, num = line.strip().split(' ')
            self.char_map[char] = int(num)
            self.int2phone[int(num)] = char
        f.close()
        self.int2phone[0] = '#'
        
        #read the label file
        label_dict = dict()
        f = open(label_file, 'r')
        for label in f.readlines():
            label = label.strip()
            label_list = []
            if self.out_type == 'char':
                utt = label.split('\t', 1)[0]
                label = label.split('\t', 1)[1]
                for i in range(len(label)):
                    if label[i].lower() in self.char_map:
                        label_list.append(self.char_map[label[i].lower()])
                    if label[i] == ' ':
                        label_list.append(28)
            else:
                label = label.split()
                utt = label[0]
                for i in range(1,len(label)):
                    label_list.append(self.char_map[label[i]])
            label_dict[utt] = np.array(label_list)
        f.close()
        
        #extract spectrum
        spec_dict = dict()
        f = open(wav_path, 'r')
        for line in f.readlines():
            utt, path = line.strip().split()
            spect = self.parse_audio(path)
            #print(spect)
            spec_dict[utt] = spect.numpy()
        f.close()
        
        if len(spec_dict) != len(label_dict):
            print("%s data: The num of wav and text are not the same!" % self.data_set)
            sys.exit(1)

        self.features_label = []
        #save the data as h5 file
        f = h5py.File(h5_file, 'w')
        f.create_dataset("phone_map_key", data=self.char_map.keys())
        f.create_dataset("phone_map_value", data = self.char_map.values())
        for utt in spec_dict:
            grp = f.create_group(utt)
            self.features_label.append((torch.FloatTensor(spec_dict[utt]), label_dict[utt].tolist()))
            grp.create_dataset('data', data=spec_dict[utt])
            grp.create_dataset('label', data=label_dict[utt])
        print("Saved the %s data to h5py file" % self.data_set)

    
    def parse_audio(self, path):
        y = load_audio(path)
        n_fft = int(audio_conf['sample_rate']*audio_conf["window_size"])
        win_length = n_fft
        hop_length = int(audio_conf['sample_rate']*audio_conf['window_stride'])
        window = windows[audio_conf['window']]
        D = librosa.stft(y, n_fft=n_fft, hop_length=hop_length,
                            win_length=win_length, window=window)
        spect, phase = librosa.magphase(D)
        spect = np.log1p(spect)
        spect = torch.FloatTensor(spect)
        if self.normalize:
            mean = spect.mean()
            std = spect.std()
            spect.add_(-mean)
            spect.div_(std)
        
        return spect.transpose(0,1)

    def load_h5py(self, h5_file):
        self.features_label = []
        f = h5py.File(h5_file, 'r')
        for grp in f:
            if grp != 'phone_map_key' and grp != 'phone_map_value':
                self.features_label.append((torch.FloatTensor(np.asarray(f[grp]['data'])), np.asarray(f[grp]['label']).tolist()))
        self.char_map = dict()
        self.int2phone = dict()
        keys = f['phone_map_key']
        values = f['phone_map_value']
        for i in range(len(keys)):
            self.char_map[str(keys[i])] = values[i]
            self.int2phone[values[i]] = keys[i]
        self.int2phone[0]='#'
        print("Load %d sentences from %s dataset" % (self.__len__(), self.data_set))

    def __getitem__(self, idx):
        return self.features_label[idx]

    def __len__(self):
        return len(self.features_label) 

def create_RNN_input(batch):
    def func(p):
        return p[0].size(0)
    
    #sort batch according to the frame nums
    batch = sorted(batch, reverse=True, key=func)
    longest_sample = batch[0][0]
    feat_size = longest_sample.size(1)
    #feat_size = 101
    max_length = longest_sample.size(0)
    batch_size = len(batch)
    inputs = torch.zeros(batch_size, max_length, feat_size)
    input_sizes = torch.IntTensor(batch_size)
    target_sizes = torch.IntTensor(batch_size)
    targets = []
    input_size_list = []
    for x in range(batch_size):
        sample = batch[x]
        feature = sample[0]
        #feature = sample[0].transpose(0,1)[:101].transpose(0,1)
        label = sample[1]
        seq_length = feature.size(0)
        inputs[x].narrow(0, 0, seq_length).copy_(feature)
        input_sizes[x] = seq_length
        input_size_list.append(seq_length)
        target_sizes[x] = len(label)
        targets.extend(label)
    targets = torch.IntTensor(targets)
    return inputs, targets, input_sizes, input_size_list, target_sizes 

#class torch.utils.data.DataLoader(dataset, batch_size=1, shuffle=False, 
#                           sampler=None, batch_sampler=None, num_workers=0, 
#                           collate_fn=<function default_collate>, 
#                           pin_memory=False, drop_last=False)
#subclass of DataLoader and rewrite the collate_fn to form batch

class myDataLoader(DataLoader):
    def __init__(self, *args, **kwargs):
        super(myDataLoader, self).__init__(*args, **kwargs)
        self.collate_fn = create_RNN_input

class myCNNDataLoader(DataLoader):
    def __init__(self, *args, **kwargs):
        super(myCNNDataLoader, self).__init__(*args, **kwargs)
        self.collate_fn = create_CNN_input

def create_CNN_input(batch):
    def func(p):
        return p[0].size(0)
    
    def change_size(size):
        size = int(math.floor((size-11)/2)+1)
        size = int(math.floor((size-11)/1)+1)
        return size

    #sort batch according to the frame nums
    batch = sorted(batch, reverse=True, key=func)
    longest_sample = batch[0][0]
    feat_size = longest_sample.size(1)
    max_length = longest_sample.size(0)
    batch_size = len(batch)
    inputs = torch.zeros(batch_size, 1, max_length, feat_size)
    input_sizes = torch.IntTensor(batch_size)
    target_sizes = torch.IntTensor(batch_size)
    targets = []
    input_size_list = []
    for x in range(batch_size):
        sample = batch[x]
        feature = sample[0]
        label = sample[1]
        seq_length = feature.size(0)
        inputs[x][0].narrow(0, 0, seq_length).copy_(feature)
        input_sizes[x] = change_size(seq_length)
        input_size_list.append(change_size(seq_length))
        target_sizes[x] = len(label)
        targets.extend(label)
    targets = torch.IntTensor(targets)
    return inputs, targets, input_sizes, input_size_list, target_sizes 

if __name__ == '__main__':
    dev_dataset = myDataset(data_set='dev', feature_type="spectrum", out_type='phone', n_feats=40)
    dev_loader = myDataLoader(dev_dataset, batch_size=8, shuffle=True, 
                     num_workers=4, pin_memory=False)
    print(dev_dataset.int2phone)
    i = 0
    for data in dev_loader:
        if i == 0:
            print(data)
        i += 1

