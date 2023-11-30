import torch
import math
import os
import sys
import torch.nn as nn
import torch.nn.functional as F


sys.path.append("../utils")
from metrics import cd, fscore, emd
from mm3d_pn2 import furthest_point_sample, gather_points, grouping_operation, ball_query, three_nn

class Poisson:
    
    def __init__(self, number_of_points, radius, max_x, max_y, max_z):
        
        self.k = number_of_points
        self.r = radius
        
        self.max_length = max_x
        self.max_width = max_y
        self.max_depth = max_z
        
        self.a = radius/np.sqrt(3)
        
        #Voxelization 
        #number of voxels
        
        self.nx, self.ny, self.nz = int(max_x/self.a)+1, int(max_y/self.a)+1, int(max_z/self.a)+1
        
        self.reset_voxel()
     
        
     #reseting vozels and initializing as null
     #Step 0
    def reset_voxel(self):
        
         
        cordinates_xyz = [(x_cor, y_cor, z_cor) for x_cor in range(self.nx)
                                                for y_cor in range(self.ny)
                                                for z_cor in range(self.nz)]
         
         #initiaizing to Null
         #Creating a dictionary of all the voxels
        self.voxels = {coords : None for coords in cordinates_xyz}
         
         
    def get_cell_coords(self, point):
        """Get the coordinates of the voxel in which point = (x,y,z) lies in."""

        return int(point[0] // self.a), int(point[1] // self.a), int(point[2] // self.a)
    
    def get_neighbour(self, coords):
        
        
        dxdydz = [(-1,-2,-1),(0,-2,-1),(1,-2, -1),(-2,-1, -1),(-1,-1, -1),(0,-1, -1),(1,-1, -1),(2,-1, -1),
                (-2,0, -1),(-1,0, -1),(1,0, -1),(2,0, -1),(-2,1,-1),(-1,1,-1),(0,1,-1),(1,1,-1),(2,1,-1),
                (-1,2,-1),(0,2,-1),(1,2,-1),(0,0,-1),(-1,-2, 0),(0,-2, 0),(1,-2, 0),(-2,-1, 0),(-1,-1, 0),(0,-1, 0),(1,-1, 0),(2,-1,0),
                (-2,0, 0),(-1,0,0),(1,0,0),(2,0,0),(-2,1,0),(-1,1,0),(0,1,0),(1,1,0),(2,1,0),
                (-1,2,0),(0,2,0),(1,2,0),(0,0,0),(-1,-2,1),(0,-2, 1),(1,-2, 1),(-2,-1, 1),(-1,-1,1),(0,-1,1),(1,-1,1),(2,-1,1),
                (-2,0,1),(-1,0,1),(1,0,1),(2,0,1),(-2,1,1),(-1,1,1),(0,1,1),(1,1,1),(2,1,1),
                (-1,2,1),(0,2,1),(1,2,1),(0,0,1)]
        
        neighbours = []
        for dx, dy, dz in dxdydz:
            neighbour_coords = coords[0] + dx, coords[1] + dy, coords[2] + dz
            if not (0 <= neighbour_coords[0] < self.nx and
                    0 <= neighbour_coords[1] < self.ny and
                    0 <= neighbour_coords[2] < self.nz) :
                # We're off the grid: no neighbours here.
                continue
            neighbour_cell = self.voxels[neighbour_coords]
            if neighbour_cell is not None:
                # This cell is occupied: store the index of the contained point
                neighbours.append(neighbour_cell)
        return neighbours
    
        
    def point_valid(self, pt):
        

        cell_coords = self.get_cell_coords(pt)
        for idx in self.get_neighbour(cell_coords):
            nearby_pt = self.samples[idx]
            # Squared distance between candidate point, pt, and this nearby_pt.
            distance2 = (nearby_pt[0]-pt[0])**2 + (nearby_pt[1]-pt[1])**2 + (nearby_pt[2]-pt[2])**2
            if distance2 < self.r**2:
                # The points are too close, so pt is not a candidate.
                return False
        # All points tested: if we're here, pt is valid
        return True
    
    def get_point(self, refpt):

        i = 0
        while i < self.k:
            rho, theta, yaw = (np.random.uniform(self.r, 2*self.r),
                          np.random.uniform(0, 2*np.pi),
                          np.random.uniform(0, 2*np.pi))
            pt = refpt[0] + rho*np.sin(theta)*np.cos(yaw), refpt[1] + rho*np.sin(theta)*np.sin(yaw) , refpt[2] + rho*np.cos(theta)
            if not (0 <= pt[0] < self.max_length and 0 <= pt[1] < self.max_width and 0<= pt[2] < self.max_depth):
                # This point falls outside the domain, so try again.
                continue
            if self.point_valid(pt):
                return pt
            i += 1
        # We failed to find a suitable point in the vicinity of refpt.
        return False
       
    def sample(self):
   
        pt = (np.random.uniform(0, self.max_length),
              np.random.uniform(0, self.max_width),
              np.random.uniform(0, self.max_depth))
        self.samples = [pt]
     
        self.voxels[self.get_cell_coords(pt)] = 0
   
        active = [0]

        while active:
      
            idx = np.random.choice(active)
            refpt = self.samples[idx]
            # Try to pick a new point relative to the reference point.
            pt = self.get_point(refpt)
            if pt:
                # Point pt is valid: add it to samples list and mark as active
                self.samples.append(pt)
                nsamples = len(self.samples) - 1
                active.append(nsamples)
                self.voxels[self.get_cell_coords(pt)] = nsamples
            else:
                # We had to give up looking for valid points near refpt, so
                # remove it from the list of "active" points.
                active.remove(idx)

        return self.samples
class EF_expansion(nn.Module):
    def __init__(self, input_size, output_size=64, step_ratio=2, k=4):
        super(EF_expansion, self).__init__()
        self.step_ratio = step_ratio
        self.k = k
        self.input_size = input_size
        self.output_size = output_size

        self.conv1 = nn.Conv2d(input_size * 2, output_size, 1)
        self.conv2 = nn.Conv2d(input_size * 2 + output_size, output_size * step_ratio, 1)
        self.conv3 = nn.Conv2d(output_size, output_size, 1)

    def forward(self, x):
        batch_size, _, num_points = x.size()

        input_edge_feature = get_graph_feature(x, self.k, minus_center=False).permute(0, 1, 3,
                                                                                      2).contiguous()  # B C K N
        edge_feature = self.conv1(input_edge_feature)
        edge_feature = F.relu(torch.cat((edge_feature, input_edge_feature), 1))

        edge_feature = F.relu(self.conv2(edge_feature))  # B C K N
        edge_feature = edge_feature.permute(0, 2, 3, 1).contiguous().view(batch_size, self.k,
                                                                          num_points * self.step_ratio,
                                                                          self.output_size).permute(0, 3, 1,
                                                                                                    2)  # B C K N

        edge_feature = self.conv3(edge_feature)
        edge_feature, _ = torch.max(edge_feature, 2)

        return edge_feature


def attention(query, key, value, mask=None):
    d_k = query.size(-1)
    scores = torch.matmul(query, key.transpose(-2, -1).contiguous()) / math.sqrt(d_k)  # B x 4 x points x points
    if mask is not None:
        scores = scores.masked_fill(mask == 0, -1e9)
    p_attn = F.softmax(scores, dim=-1)
    return torch.matmul(p_attn, value), p_attn


def calc_cd(output, gt, calc_f1=False):
    # cham_loss = dist_chamfer_3D.chamfer_3DDist()
    cham_loss = cd()
    dist1, dist2, _, _ = cham_loss(gt, output)
    cd_p = (torch.sqrt(dist1).mean(1) + torch.sqrt(dist2).mean(1)) / 2
    cd_t = (dist1.mean(1) + dist2.mean(1))
    if calc_f1:
        f1, _, _ = fscore(dist1, dist2)
        return cd_p, cd_t, f1
    else:
        f1, _, _ = fscore(dist1, dist2)
        return cd_p, cd_t, f1

def calc_cd_no_f1(output, gt, calc_f1=False):
    # cham_loss = dist_chamfer_3D.chamfer_3DDist()
    cham_loss = cd()
    dist1, dist2, _, _ = cham_loss(gt, output)
    return dist1, dist2


def calc_emd(output, gt, eps=0.005, iterations=50):
    # emd_loss = emd.emdModule()
    emd_loss = emd()
    dist, _ = emd_loss(output, gt, eps, iterations)
    emd_out = torch.sqrt(dist).mean(1)
    return emd_out


def edge_preserve_sampling(feature_input, point_input, num_samples, k=10):
    batch_size = feature_input.size()[0]
    feature_size = feature_input.size()[1]
    num_points = feature_input.size()[2]

    p_idx = furthest_point_sample(point_input, num_samples)
    point_output = gather_points(point_input.transpose(1, 2).contiguous(), p_idx).transpose(1,
                                                                                                   2).contiguous()

    pk = int(min(k, num_points))
    _, pn_idx = knn_point(pk, point_input, point_output)
    pn_idx = pn_idx.detach().int()
    neighbor_feature = gather_points(feature_input, pn_idx.view(batch_size, num_samples * pk)).view(batch_size,
                                                                                                           feature_size,
                                                                                                           num_samples,
                                                                                                           pk)
    neighbor_feature, _ = torch.max(neighbor_feature, 3)

    center_feature = grouping_operation(feature_input, p_idx.unsqueeze(2)).view(batch_size, -1, num_samples)

    net = torch.cat((center_feature, neighbor_feature), 1)

    return net, p_idx, pn_idx, point_output


def get_edge_features(x, idx):
    batch_size, num_points, k = idx.size()
    device = torch.device('cuda')
    idx_base = torch.arange(0, batch_size, device=device).view(-1, 1, 1) * num_points
    idx = idx + idx_base
    idx = idx.view(-1)
    x = x.squeeze(2)
    _, num_dims, _ = x.size()
    x = x.transpose(2, 1).contiguous()
    feature = x.view(batch_size * num_points, -1)[idx, :]
    feature = feature.view(batch_size, num_points, k, num_dims).permute(0, 3, 2, 1)  # B, C, K, N
    return feature


def gen_grid(num_grid_point):
    x = torch.linspace(-0.05, 0.05, steps=num_grid_point)
    x, y = torch.meshgrid(x, x)
    grid = torch.stack([x, y], axis=-1).view(2, num_grid_point ** 2)
    return grid


def gen_1d_grid(num_grid_point):
    x = torch.linspace(-0.05, 0.05, num_grid_point)
    grid = x.view(1, num_grid_point)
    return grid


def gen_grid_up(up_ratio, grid_size=0.2):
    sqrted = int(math.sqrt(up_ratio)) + 1
    for i in range(1, sqrted + 1).__reversed__():
        if (up_ratio % i) == 0:
            num_x = i
            num_y = up_ratio // i
            break

    grid_x = torch.linspace(-grid_size, grid_size, steps=num_x)
    grid_y = torch.linspace(-grid_size, grid_size, steps=num_y)

    x, y = torch.meshgrid(grid_x, grid_y)  # x, y shape: (2, 1)
    grid = torch.stack([x, y], dim=-1).view(-1, 2).transpose(0, 1).contiguous()
    return grid


def get_graph_feature(x, k=20, minus_center=True):
    idx = knn(x, k=k)
    batch_size, num_points, _ = idx.size()
    device = torch.device('cuda')

    idx_base = torch.arange(0, batch_size, device=device).view(-1, 1, 1) * num_points

    idx = idx + idx_base

    idx = idx.view(-1)

    _, num_dims, _ = x.size()

    x = x.transpose(2, 1).contiguous()
    feature = x.view(batch_size * num_points, -1)[idx, :]
    feature = feature.view(batch_size, num_points, k, num_dims)
    x = x.view(batch_size, num_points, 1, num_dims).repeat(1, 1, k, 1)

    if minus_center:
        feature = torch.cat((x, feature - x), dim=3).permute(0, 3, 1, 2)
    else:
        feature = torch.cat((x, feature), dim=3).permute(0, 3, 1, 2)
    return feature


def get_repulsion_loss(pred, nsample=20, radius=0.07):
    # pred: (batch_size, npoint,3)
    # idx = pn2.ball_query(radius, nsample, pred, pred)
    idx = knn(pred.transpose(1, 2).contiguous(), nsample).int()
    pred_flipped = pred.transpose(1, 2).contiguous()
    grouped_pred = grouping_operation(pred_flipped, idx)  # (B, C, npoint, nsample)
    grouped_pred -= pred_flipped.unsqueeze(-1)

    # get the uniform loss
    h = 0.03
    dist_square = torch.sum(grouped_pred ** 2, dim=1)
    dist_square, idx = torch.topk(-dist_square, 5)
    dist_square = -dist_square[:, :, 1:]  # remove the first one
    dist_square = torch.max(torch.FloatTensor([1e-12]).expand_as(dist_square).cuda(), dist_square)
    dist = torch.sqrt(dist_square)
    weight = torch.exp(-dist_square / h ** 2)
    uniform_loss = torch.mean(radius - dist * weight)
    return uniform_loss


def get_uniform_loss(pcd, percentages=[0.004, 0.006, 0.008, 0.010, 0.012], radius=1.0):
    B, N, C = pcd.size()
    npoint = int(N * 0.05)
    loss = 0
    for p in percentages:
        nsample = int(N*p)
        r = math.sqrt(p*radius)
        disk_area = math.pi * (radius ** 2) * p/nsample
        new_xyz = gather_points(pcd.transpose(1, 2).contiguous(),
                                       furthest_point_sample(pcd, npoint)).transpose(1, 2).contiguous()
        idx = ball_query(0, r, nsample, pcd, new_xyz)
        expect_len = math.sqrt(disk_area)

        grouped_pcd = grouping_operation(pcd.transpose(1,2).contiguous(), idx)
        grouped_pcd = grouped_pcd.permute(0, 2, 3, 1).contiguous().view(-1, nsample, 3)

        var, _ = knn_point(2, grouped_pcd, grouped_pcd)
        uniform_dis = -var[:, :, 1:]

        uniform_dis = torch.sqrt(torch.abs(uniform_dis+1e-8))
        uniform_dis = torch.mean(uniform_dis, dim=-1)
        uniform_dis = ((uniform_dis - expect_len)**2 / (expect_len + 1e-8))

        mean = torch.mean(uniform_dis)
        mean = mean*math.pow(p*100,2)
        loss += mean
    return loss/len(percentages)


def index_points(points, idx):
    device = points.device
    B = points.shape[0]
    view_shape = list(idx.shape)
    view_shape[1:] = [1] * (len(view_shape) - 1)
    repeat_shape = list(idx.shape)
    repeat_shape[0] = 1
    batch_indices = torch.arange(B, dtype=torch.long).to(device).view(view_shape).repeat(repeat_shape)
    new_points = points[batch_indices, idx, :]
    return new_points


def knn(x, k): 
    inner = -2 * torch.matmul(x.transpose(2, 1).contiguous(), x)
    xx = torch.sum(x ** 2, dim=1, keepdim=True)
    pairwise_distance = -xx - inner - xx.transpose(2, 1).contiguous()
    idx = pairwise_distance.topk(k=k, dim=-1)[1]
    return idx


def knn_point(pk, point_input, point_output):
    m = point_output.size()[1]
    n = point_input.size()[1]

    inner = -2 * torch.matmul(point_output, point_input.transpose(2, 1).contiguous())
    xx = torch.sum(point_output ** 2, dim=2, keepdim=True).repeat(1, 1, n)
    yy = torch.sum(point_input ** 2, dim=2, keepdim=False).unsqueeze(1).repeat(1, m, 1)
    pairwise_distance = -xx - inner - yy
    dist, idx = pairwise_distance.topk(k=pk, dim=-1)
    return dist, idx


def knn_point_all(pk, point_input, point_output):
    m = point_output.size()[1]
    n = point_input.size()[1]

    inner = -2 * torch.matmul(point_output, point_input.transpose(2, 1).contiguous())
    xx = torch.sum(point_output ** 2, dim=2, keepdim=True).repeat(1, 1, n)
    yy = torch.sum(point_input ** 2, dim=2, keepdim=False).unsqueeze(1).repeat(1, m, 1)
    pairwise_distance = -xx - inner - yy
    dist, idx = pairwise_distance.topk(k=pk, dim=-1)

    return dist, idx


def symmetric_sample(points, num=512):
    p1_idx = furthest_point_sample(points, num)
    input_fps = gather_points(points.transpose(1, 2).contiguous(), p1_idx).transpose(1, 2).contiguous()
    x = torch.unsqueeze(input_fps[:, :, 0], dim=2)
    y = torch.unsqueeze(input_fps[:, :, 1], dim=2)
    z = torch.unsqueeze(-input_fps[:, :, 2], dim=2)
    input_fps_flip = torch.cat([x, y, z], dim=2)
    input_fps = torch.cat([input_fps, input_fps_flip], dim=1)
    return input_fps


def three_nn_upsampling(target_points, source_points):
    dist, idx = three_nn(target_points, source_points)
    dist = torch.max(dist, torch.ones(1).cuda() * 1e-10)
    norm = torch.sum((1.0 / dist), 2, keepdim=True)
    norm = norm.repeat(1, 1, 3)
    weight = (1.0 / dist) / norm

    return idx, weight
def index_points_2(points, idx):
    """
    Input:
        points: input points data, [B, N, C]
        idx: sample index data, [B, S, [K]]
    Return:
        new_points:, indexed points data, [B, S, [K], C]
    """
    raw_size = idx.size()
    idx = idx.reshape(raw_size[0], -1)
    res = torch.gather(points, 1, idx[..., None].expand(-1, -1, points.size(-1)))
    return res.reshape(*raw_size, -1)