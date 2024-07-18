# Copyright (c) 2024 Minmin Gong
#

from pathlib import Path
import shutil

import importlib
from nvdiffrast.torch.ops import _cached_plugin

import numpy as np
import torch
from pytorch_lightning import seed_everything
from PIL import Image
from huggingface_hub import hf_hub_download

from src.models.lrm_mesh import InstantMesh
from src.utils.camera_util import get_zero123plus_input_cameras
from src.utils.mesh_util import save_obj, save_obj_with_mtl

class MeshGenerator:
    def __init__(self):
        this_py_dir = Path(__file__).parent.resolve()

        try:
            # Inject the cached binary into nvdiffrast to prevent recompiling
            _cached_plugin[False] = importlib.import_module("nvdiffrast_plugin")
        except:
            pass

        seed_everything(42)

        radius = 4

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        self.model = InstantMesh(encoder_freeze = False, encoder_model_name = "facebook/dino-vitb16", encoder_feat_dim = 768,
            transformer_dim = 1024, transformer_layers = 16, transformer_heads = 16, triplane_low_res = 32,
            triplane_high_res = 64, triplane_dim = 80, rendering_samples_per_ray = 128, grid_res = 128, grid_scale = 2.1
        )

        model_ckpt_path = this_py_dir.joinpath("Models/instant_mesh_large.ckpt")
        if not model_ckpt_path.exists():
            print("Downloading pre-trained mesh generator models...")
            downloaded_model_ckpt_path = hf_hub_download(repo_id = "TencentARC/InstantMesh", filename = model_ckpt_path.name, repo_type = "model")
            shutil.copyfile(downloaded_model_ckpt_path, model_ckpt_path)

        state_dict = torch.load(model_ckpt_path, map_location = "cpu")["state_dict"]
        state_dict = {k[14 : ] : v for k, v in state_dict.items() if k.startswith("lrm_generator.")}
        self.model.load_state_dict(state_dict, strict = True)

        self.model = self.model.to(self.device)
        self.model.init_flexicubes_geometry(self.device, fovy = 30.0)
        self.model.eval()

        self.input_cameras = get_zero123plus_input_cameras(batch_size = 1, radius = radius).to(self.device)

    def Gen(self, images, texture_size, output_mesh_path : Path):
        mv_images = torch.empty(6, 3, 320, 320) # views, channels, height, width
        for i in range(0, 6):
            assert(images[i].size == (320, 320))
            mv_image = np.asarray(images[i], dtype = np.float32)
            mv_images[i] = torch.from_numpy(mv_image).permute(2, 0, 1).contiguous()

        mv_images = mv_images.to(self.device)
        mv_images /= 255.0
        mv_images = mv_images.clamp(0, 1)
        mv_images = mv_images.unsqueeze(0)

        with torch.no_grad():
            planes = self.model.forward_planes(mv_images, self.input_cameras)

            export_texmap = True

            mesh_out = self.model.extract_mesh(
                planes,
                use_texture_map = export_texmap,
                texture_resolution = texture_size
            )
            if export_texmap:
                vertices, faces, uvs, mesh_tex_idx, tex_map = mesh_out
                save_obj_with_mtl(
                    vertices.data.cpu().numpy(),
                    uvs.data.cpu().numpy(),
                    faces.data.cpu().numpy(),
                    mesh_tex_idx.data.cpu().numpy(),
                    tex_map.permute(1, 2, 0).data.cpu().numpy(),
                    output_mesh_path
                )
            else:
                vertices, faces, vertex_colors = mesh_out
                save_obj(vertices, faces, vertex_colors, output_mesh_path)
