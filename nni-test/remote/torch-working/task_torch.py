# Model: Lenet
# Dataset: MNIST
# Framework: PyTorch

from __future__ import print_function

import argparse
import logging
import os

from torchvision import datasets, transforms
import torch
import torch.distributed as dist
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import model_torch


WORLD_SIZE = int(os.environ.get('WORLD_SIZE', 1))


def train(args, model, device, train_loader, optimizer, epoch):
    model.train()
    for batch_idx, (data, target) in enumerate(train_loader):
        data, target = data.to(device), target.to(device)
        optimizer.zero_grad()
        output = model(data)
        loss = F.nll_loss(output, target)
        loss.backward()
        optimizer.step()
        if batch_idx % args.log_interval == 0:
            msg = 'Train Epoch: {} [{}/{} ({:.0f}%)]\tloss={:.4f}'.format(
                epoch, batch_idx * len(data), len(train_loader.dataset),
                       100. * batch_idx / len(train_loader), loss.item())
            print(msg)
            logging.debug(msg)
            niter = epoch * len(train_loader) + batch_idx


def test(args, model, device, test_loader, epoch):
    model.eval()
    test_loss = 0
    correct = 0
    with torch.no_grad():
        for data, target in test_loader:
            data, target = data.to(device), target.to(device)
            output = model(data)
            test_loss += F.nll_loss(output, target, reduction='sum').item()  # sum up batch loss
            pred = output.max(1, keepdim=True)[1]  # get the index of the max log-probability
            correct += pred.eq(target.view_as(pred)).sum().item()

    test_loss /= len(test_loader.dataset)
    logging.info('\n{{metricName: accuracy, metricValue: {:.4f}}};{{metricName: loss, metricValue: {:.4f}}}\n'.format(
        float(correct) / len(test_loader.dataset), test_loss))


def should_distribute():
    return dist.is_available() and WORLD_SIZE > 1


def is_distributed():
    return dist.is_available() and dist.is_initialized()


def build_model():
    # Training settings
    parser = argparse.ArgumentParser(description='PyTorch MNIST Example')
    parser.add_argument('--batch-size', type=int, default=64, metavar='N',
                        help='input batch size for training (default: 64)')
    parser.add_argument('--test-batch-size', type=int, default=1000, metavar='N',
                        help='input batch size for testing (default: 1000)')
    parser.add_argument('--epochs', type=int, default=10, metavar='N',
                        help='number of epochs to train (default: 10)')
    parser.add_argument('--lr', type=float, default=0.01, metavar='LR',
                        help='learning rate (default: 0.01)')
    parser.add_argument('--momentum', type=float, default=0.5, metavar='M',
                        help='SGD momentum (default: 0.5)')
    parser.add_argument('--no-cuda', action='store_true', default=False,
                        help='disables CUDA training')
    parser.add_argument('--seed', type=int, default=1, metavar='S',
                        help='random seed (default: 1)')
    parser.add_argument('--log-interval', type=int, default=10, metavar='N',
                        help='how many batches to wait before logging training status')
    parser.add_argument('--save-model', action='store_true', default=False,
                        help='For Saving the current Model')
    if dist.is_available():
        parser.add_argument('--backend', type=str, help='Distributed backend',
                            choices=[dist.Backend.GLOO, dist.Backend.NCCL, dist.Backend.MPI],
                            default=dist.Backend.GLOO)
    args = parser.parse_args()
    use_cuda = not args.no_cuda and torch.cuda.is_available()
    if use_cuda:
        print('Using CUDA')

    torch.manual_seed(args.seed)

    device = torch.device("cuda" if use_cuda else "cpu")

    if should_distribute():
        print('Using dist-learning PyTorch with {} backend'.format(args.backend))
        dist.init_process_group(backend=args.backend)

    kwargs = {'num_workers': 1, 'pin_memory': True} if use_cuda else {}
    train_loader = torch.utils.data.DataLoader(
        datasets.MNIST('../s', train=True, download=True,
                       transform=transforms.Compose([
                           transforms.ToTensor(),
                           transforms.Normalize((0.1307,), (0.3081,))
                       ])),
        batch_size=args.batch_size, shuffle=True, **kwargs)
    test_loader = torch.utils.data.DataLoader(
        datasets.MNIST('../s', train=False, transform=transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize((0.1307,), (0.3081,))
        ])),
        batch_size=args.test_batch_size, shuffle=False, **kwargs)

    model = model_torch.LeNet().to(device)

    if is_distributed():
        Distributor = nn.parallel.DistributedDataParallel if use_cuda \
            else nn.parallel.DistributedDataParallelCPU
        model = Distributor(model)

    optimizer = optim.SGD(model.parameters(), lr=args.lr, momentum=args.momentum)

    for epoch in range(1, args.epochs + 1):
        train(args, model, device, train_loader, optimizer, epoch)
        test(args, model, device, test_loader, epoch)

    if (args.save_model):
        torch.save(model.state_dict(), "mnist_cnn.pt")


if __name__ == '__main__':
    build_model()
