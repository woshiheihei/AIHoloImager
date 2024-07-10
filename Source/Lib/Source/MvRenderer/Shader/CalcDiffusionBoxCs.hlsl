// Copyright (c) 2024 Minmin Gong
//

#define BLOCK_DIM 16
#define MIN_WAVE_SIZE 32

cbuffer param_cb : register(b0)
{
    uint4 atlas_offset_view_size;
};

Texture2D diffusion_tex : register(t0);

RWTexture2D<uint> bounding_box_tex : register(u0);

groupshared uint2 group_wave_mins[BLOCK_DIM * BLOCK_DIM / MIN_WAVE_SIZE];
groupshared uint2 group_wave_maxs[BLOCK_DIM * BLOCK_DIM / MIN_WAVE_SIZE];

[numthreads(BLOCK_DIM, BLOCK_DIM, 1)]
void main(uint3 dtid : SV_DispatchThreadID, uint group_index : SV_GroupIndex)
{
    const float ValidThreshold = 237 / 255.0f;

    uint2 atlas_offset = atlas_offset_view_size.xy;
    uint2 view_size = atlas_offset_view_size.zw;

    uint2 bb_min = view_size;
    uint2 bb_max = uint2(0, 0);
    if (all(dtid.xy < view_size))
    {
        float3 rgb = diffusion_tex.Load(uint3(atlas_offset + dtid.xy, 0)).rgb;
        if (any(rgb < ValidThreshold))
        {
            bb_min = dtid.xy;
            bb_max = dtid.xy;
        }
    }

    uint wave_size = WaveGetLaneCount();
    uint wave_index = group_index / wave_size;
    uint lane_index = WaveGetLaneIndex();

    bb_min = WaveActiveMin(bb_min);
    bb_max = WaveActiveMax(bb_max);
    if (WaveIsFirstLane())
    {
        group_wave_mins[wave_index] = bb_min;
        group_wave_maxs[wave_index] = bb_max;
    }
    GroupMemoryBarrierWithGroupSync();

    uint group_mem_size = BLOCK_DIM * BLOCK_DIM / wave_size;

    if (group_index < group_mem_size)
    {
        bb_min = group_wave_mins[group_index];
        bb_max = group_wave_maxs[group_index];
    }
    GroupMemoryBarrier();

    if (group_index < group_mem_size)
    {
        bb_min = WaveActiveMin(bb_min);
        bb_max = WaveActiveMax(bb_max);
    }

    if (group_index == 0)
    {
        InterlockedMin(bounding_box_tex[uint2(0, 1)], bb_min.x);
        InterlockedMin(bounding_box_tex[uint2(1, 1)], bb_min.y);
        InterlockedMax(bounding_box_tex[uint2(2, 1)], bb_max.x);
        InterlockedMax(bounding_box_tex[uint2(3, 1)], bb_max.y);
    }
}
