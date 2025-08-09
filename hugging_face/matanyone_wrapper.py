import tqdm
import torch
from torchvision.transforms.functional import to_tensor
import numpy as np
import random
import cv2
from matanyone.utils.device import get_default_device, safe_autocast_decorator

device = get_default_device()

def gen_dilate(alpha, min_kernel_size, max_kernel_size): 
    kernel_size = random.randint(min_kernel_size, max_kernel_size)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size,kernel_size))
    fg_and_unknown = np.array(np.not_equal(alpha, 0).astype(np.float32))
    dilate = cv2.dilate(fg_and_unknown, kernel, iterations=1)*255
    return dilate.astype(np.float32)

def gen_erosion(alpha, min_kernel_size, max_kernel_size): 
    kernel_size = random.randint(min_kernel_size, max_kernel_size)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size,kernel_size))
    fg = np.array(np.equal(alpha, 255).astype(np.float32))
    erode = cv2.erode(fg, kernel, iterations=1)*255
    return erode.astype(np.float32)

@torch.inference_mode()
@safe_autocast_decorator()
def matanyone(processor, frames_np, mask, r_erode=0, r_dilate=0, n_warmup=10):
    """
    Args:
        frames_np: [(H,W,C)]*n, uint8
        mask: (H,W), uint8
    Outputs:
        com: [(H,W,C)]*n, uint8
        pha: [(H,W,C)]*n, uint8
    """

    # print(f'===== [r_erode] {r_erode}; [r_dilate] {r_dilate} =====')
    bgr = (np.array([127, 127, 127], dtype=np.float32)/255).reshape((1, 1, 3))
    objects = [1]

    # [optional] erode & dilate on given seg mask
    if r_dilate > 0:
        mask = gen_dilate(mask, r_dilate, r_dilate)
    if r_erode > 0:
        mask = gen_erosion(mask, r_erode, r_erode)

    mask = torch.from_numpy(mask).to(device)

    frames_np = [frames_np[0]]* n_warmup + frames_np

    frames = []
    phas = []
    for ti, frame_single in tqdm.tqdm(enumerate(frames_np)):
        image = to_tensor(frame_single).float().to(device)

        if ti == 0:
            output_prob = processor.step(image, mask, objects=objects)      # encode given mask
            output_prob = processor.step(image, first_frame_pred=True)      # clear past memory for warmup frames
        else:
            if ti <= n_warmup:
                output_prob = processor.step(image, first_frame_pred=True)  # clear past memory for warmup frames
            else:
                output_prob = processor.step(image)

        # convert output probabilities to an object mask
        mask = processor.output_prob_to_mask(output_prob)

        pha = mask.unsqueeze(2).detach().to("cpu").numpy()
        com_np = frame_single / 255. * pha + bgr * (1 - pha)
        
        # DONOT save the warmup frames
        if ti > (n_warmup-1):
            frames.append((com_np*255).astype(np.uint8))
            phas.append(((1 - pha) * 255).astype(np.uint8))
    
    return frames, phas
