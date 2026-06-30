import torch
from omnivoice import OmniVoice
print('Import successful')
model = OmniVoice.from_pretrained('k2-fsa/OmniVoice', device_map='cpu')
print('Model loaded')
