import torch
import torch.nn as nn
import torch.optim as optim
import torchvision
from torchvision import datasets, models, transforms
import matplotlib.pyplot as plt
import time
import os
import copy
import pandas as pd
from tqdm import tqdm
from scipy import stats
import pandas
import scipy.io
import numpy as np
import argparse
import time
import math
import os, sys
import cv2
import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error
from sklearn import preprocessing
from scipy.optimize import curve_fit
from sklearn.svm import SVR
from sklearn.svm import LinearSVR
from sklearn.model_selection import RandomizedSearchCV
import scipy.stats
from scipy.io import savemat
from concurrent import futures
import functools
import warnings
import matplotlib.pyplot as plt
from PIL import Image
warnings.filterwarnings("ignore")

use_cuda = torch.cuda.is_available()
device = torch.device("cuda" if use_cuda else "cpu")
# device = torch.device("cpu")  # for debug only
print(device)

# ----------------------- Set System logger ------------- #
class Logger:
  def __init__(self, log_file):
    self.terminal = sys.stdout
    self.log = open(log_file, "a")

  def write(self, message):
    self.terminal.write(message)
    self.log.write(message)  

  def flush(self):
    #this flush method is needed for python 3 compatibility.
    #this handles the flush command by doing nothing.
    #you might want to specify some extra behavior here.
    pass

def arg_parser():
  parser = argparse.ArgumentParser()
  parser.add_argument('--model_name', type=str, default='KONCEPT512',
                      help='Evaluated BVQA model name.')
  parser.add_argument('--dataset_name', type=str, default='YOUTUBE_UGC',
                      help='Evaluation dataset.')
  parser.add_argument('--dataset_path', type=str, default='/media/ztu/Seagate-ztu-ugc/YT_UGC/original_videos',
                      help='Dataset path.')
  parser.add_argument('--vframes_path', type=str, default='video_frames/YOUTUBE_UGC', help='Path to decoded video frames.')
  parser.add_argument('--mos_file', type=str,
                      default='/home/ztu/Desktop/git_workspace/Video-FRIQUEE/mos_feat_files/YOUTUBE_UGC_metadata.csv',
                      help='Dataset MOS scores.')
  parser.add_argument('--out_file', type=str,
                      default='result/YOUTUBE_UGC_KONCEPT512_feats.mat',
                      help='Output correlation results')
  parser.add_argument('--log_file', type=str,
                      default='logs/logs_debug.log',
                      help='Log files.')
  parser.add_argument('--color_only', action='store_true',
                      help='Evaluate color values only. (Only for YouTube UGC)')
  parser.add_argument('--log_short', action='store_true',
                      help='Whether log short')
  parser.add_argument('--use_parallel', action='store_true',
                      help='Use parallel for iterations.')
  args = parser.parse_args()
  return args

# read YUV frame from file
def read_YUVframe(f_stream, width, height, idx):
  fr_offset = 1.5
  uv_width = width // 2
  uv_height = height // 2

  f_stream.seek(idx*fr_offset*width*height)

  # Read Y plane
  Y = np.fromfile(f_stream, dtype=np.uint8, count=width*height)
  if len(Y) < width * height:
    Y = U = V = None
    return Y, U, V
  Y = Y.reshape((height, width, 1)).astype(np.float)

  # Read U plane 
  U = np.fromfile(f_stream, dtype=np.uint8, count=uv_width*uv_height)
  if len(U) < uv_width * uv_height:
    Y = U = V = None
    return Y, U, V
  U = U.reshape((uv_height, uv_width, 1)).repeat(2, axis=0).repeat(2, axis=1).astype(np.float)
  # U = cv2.resize(U, (width, height), interpolation=cv2.INTER_CUBIC)

  # Read V plane
  V = np.fromfile(f_stream, dtype=np.uint8, count=uv_width*uv_height)
  if len(V) < uv_width * uv_height:
    Y = U = V = None
    return Y, U, V
  V = V.reshape((uv_height, uv_width, 1)).repeat(2, axis=0).repeat(2, axis=1).astype(np.float)
  # V = cv2.resize(V, (width, height), interpolation=cv2.INTER_CUBIC)
  YUV = np.concatenate((Y, U, V), axis=2)
  return YUV

# ref: https://gist.github.com/chenhu66/41126063f114410a6c8ce5c3994a3ce2
import numpy as np
#input is a RGB numpy array with shape (height,width,3), can be uint,int, float or double, values expected in the range 0..255
#output is a double YUV numpy array with shape (height,width,3), values in the range 0..255
def RGB2YUV( rgb ):
    m = np.array([[ 0.29900, -0.16874,  0.50000],
                 [0.58700, -0.33126, -0.41869],
                 [ 0.11400, 0.50000, -0.08131]])
    yuv = np.dot(rgb,m)
    yuv[:,:,1:]+=128.0
    return yuv

#input is an YUV numpy array with shape (height,width,3) can be uint,int, float or double,  values expected in the range 0..255
#output is a double RGB numpy array with shape (height,width,3), values in the range 0..255
def YUV2RGB( yuv ):
    m = np.array([[ 1.0, 1.0, 1.0],
                 [-0.000007154783816076815, -0.3441331386566162, 1.7720025777816772],
                 [ 1.4019975662231445, -0.7141380310058594 , 0.00001542569043522235] ])
    rgb = np.dot(yuv,m)
    rgb[:,:,0]-=179.45477266423404
    rgb[:,:,1]+=135.45870971679688
    rgb[:,:,2]-=226.8183044444304
    return rgb.clip(0, 255).astype(np.uint8)

def YUV2RGB_OpenCV(YUV):
    YVU = YUV[:, :, [0, 2, 1]]  # swap UV 
    return cv2.cvtColor(YVU.astype(np.uint8), cv2.COLOR_YCrCb2RGB)

data_transforms = {
    'train': transforms.Compose([
#         transforms.RandomResizedCrop(input_size),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize([0.5, 0.5, 0.5], [0.5, 0.5, 0.5])
#         transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])

    ]),
    'val': transforms.Compose([
        transforms.Resize((384,512), interpolation=Image.BILINEAR),
#         transforms.CenterCrop(input_size),
        transforms.ToTensor(),
        transforms.Normalize([0.5, 0.5, 0.5], [0.5, 0.5, 0.5])
    ]),
}

from inceptionresnetv2 import inceptionresnetv2
class model_qa(nn.Module):
    def __init__(self,num_classes,**kwargs):
        super(model_qa,self).__init__()
        base_model = inceptionresnetv2(num_classes=1000, pretrained='imagenet')
        self.base= nn.Sequential(*list(base_model.children())[:-1])
        self.fc = nn.Sequential(
            nn.Linear(1536, 2048),
            nn.ReLU(inplace=True),
            nn.BatchNorm1d(2048),
            nn.Dropout(p=0.25),
            nn.Linear(2048, 1024),
            nn.ReLU(inplace=True),
            nn.BatchNorm1d(1024),
            nn.Dropout(p=0.25),
            nn.Linear(1024, 256),
            nn.ReLU(inplace=True),
            nn.BatchNorm1d(256),
            nn.Dropout(p=0.5),
            nn.Linear(256, num_classes),
        )

    def forward(self,x):
        x = self.base(x)
        x = x.view(x.size(0), -1)
        x_feats = self.fc[:-1](x)
        x = self.fc[-1](x_feats)
        return x, x_feats

def main(args):
  video_tmp = '/media/ztu/Data/tmp'  # store tmp decoded .yuv file
  if not os.path.exists(video_tmp):
    os.makedirs(video_tmp)

  out_dir = os.path.dirname(args.out_file)  # create out file parent dir if not exists
  if not os.path.exists(out_dir):
    os.makedirs(out_dir)
  
  mos_mat = pandas.read_csv(args.mos_file)
  num_videos = mos_mat.shape[0]

  feats_mat = []
  time_cnts_all = []
  # init koncept512 model only once - oom issues
  KonCept512 = model_qa(num_classes=1) 
  model_state = torch.load('./KonCept512.pth', map_location=lambda storage, loc: storage)
  KonCept512.load_state_dict(model_state)
  KonCept512 = KonCept512.to(device)
  KonCept512.eval()
  for i in range(num_videos):
    if args.dataset_name == 'KONVID_1K':
      video_name = os.path.join(args.dataset_path, str(mos_mat.loc[i, 'flickr_id'])+'.mp4')
    elif args.dataset_name == 'LIVE_VQC':
      video_name = os.path.join(args.dataset_path, mos_mat.loc[i, 'File'])
    elif args.dataset_name == 'YOUTUBE_UGC':
      video_name = os.path.join(args.dataset_path, mos_mat.loc[i, 'category'],
                                str(mos_mat.loc[i, 'resolution'])+'P',
                                mos_mat.loc[i, 'vid']+'.mkv')
    yuv_name = os.path.join(video_tmp, os.path.basename(video_name)+'.yuv')

    print(f"Computing features for {i}th sequence: {video_name}")

    # decode video and store in tmp
    cmd = 'ffmpeg -loglevel error -y -i ' + video_name + ' -pix_fmt yuv420p -vsync 0 ' + yuv_name
    os.system(cmd)

    # calculate number of frames 
    width = mos_mat.loc[i, 'width']
    height = mos_mat.loc[i, 'height']
    framerate = int(round(mos_mat.loc[i, 'framerate']))
    test_stream = open(yuv_name, 'r') 
    test_stream.seek(0, os.SEEK_END)
    filesize = test_stream.tell()
    num_frames = int(filesize/(height*width*1.5))  # for 8-bit videos
    
    frame_feats = []  # frames features
    t_cnts = []
    frames_path = os.path.join(args.vframes_path, f'{i:04}'+os.path.basename(video_name).split('.')[0])
    if not os.path.exists(frames_path):
      os.makedirs(frames_path)
    for fr in range(framerate // 2, num_frames-3, framerate):
      this_yuv = read_YUVframe(test_stream, width, height, fr)
      this_rgb_frame = YUV2RGB_OpenCV(this_yuv)
      frame = Image.fromarray(this_rgb_frame, mode='RGB')
      frame.save(os.path.join(frames_path, f'frame_{fr}.png'))
      # run koncept
      frame = data_transforms['val'](frame)
      frame = frame.unsqueeze_(0)
      frame = frame.to(device)

      t_start = time.time()
      output, output_feats = KonCept512(frame)
      t_cnts.append(time.time() - t_start)

      output = output.data.cpu().numpy()[0]
      output_feats = output_feats.data.cpu().numpy()[0]
      output_cat = np.concatenate((output, output_feats))
      frame_feats.append(output_cat)
    
    feats_mat.append(frame_feats)
    t_each = sum(t_cnts)
    print(f"Elapsed {t_each} seconds")
    time_cnts_all.append(t_each)

    #delete decoded video
    test_stream.close()
    os.remove(yuv_name)
  savemat(args.out_file, {"feats_mat": feats_mat})


if __name__ == '__main__':
  args = arg_parser()
  log_dir = os.path.dirname(args.log_file)  # create out file parent dir if not exists
  if not os.path.exists(log_dir):
    os.makedirs(log_dir)
  if not os.path.exists(args.vframes_path):
    os.makedirs(args.vframes_path)
  sys.stdout = Logger(args.log_file)
  main(args)