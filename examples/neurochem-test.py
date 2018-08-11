import os
import torch
import torchani
import ignite
import pickle
import argparse

# parse command line arguments
parser = argparse.ArgumentParser()
parser.add_argument('dataset_path',
                    help='Path of the dataset. The path can be a hdf5 file or \
                    a directory containing hdf5 files. It can also be a file \
                    dumped by pickle.')
parser.add_argument('-d', '--device',
                    help='Device of modules and tensors',
                    default=('cuda' if torch.cuda.is_available() else 'cpu'))
parser.add_argument('--chunk_size',
                    help='Number of conformations of each chunk',
                    default=256, type=int)
parser.add_argument('--batch_chunks',
                    help='Number of chunks in each minibatch',
                    default=4, type=int)
parser.add_argument('--const_file',
                    help='File storing constants',
                    default=torchani.buildin_const_file)
parser.add_argument('--sae_file',
                    help='File storing self atomic energies',
                    default=torchani.buildin_sae_file)
parser.add_argument('--network_dir',
                    help='Directory or prefix of directories storing networks',
                    default=None)
parser.add_argument('--ensemble',
                    help='Number of models in ensemble',
                    default=False)
parser = parser.parse_args()

# load modules and datasets
device = torch.device(parser.device)
aev_computer = torchani.AEVComputer(const_file=parser.const_file)
prepare = torchani.PrepareInput(aev_computer.species)
nn = torchani.models.NeuroChemNNP(aev_computer.species,
                                  from_=parser.network_dir,
                                  ensemble=parser.ensemble)
model = torch.nn.Sequential(prepare, aev_computer, nn)
container = torchani.ignite.Container({'energies': model})
container = container.to(device)

# load datasets
shift_energy = torchani.EnergyShifter(aev_computer.species, parser.sae_file)
if parser.dataset_path.endswith('.h5') or \
   parser.dataset_path.endswith('.hdf5') or \
   os.path.isdir(parser.dataset_path):
    dataset = torchani.data.ANIDataset(
        parser.dataset_path, parser.chunk_size, device=device,
        transform=[shift_energy.subtract_from_dataset])
    datasets = [dataset]
else:
    with open(parser.dataset_path, 'rb') as f:
        datasets = pickle.load(f)
        if not isinstance(datasets, list) and not isinstance(datasets, tuple):
            datasets = [datasets]


# prepare evaluator
def hartree2kcal(x):
    return 627.509 * x


for dataset in datasets:
    dataloader = torchani.data.dataloader(dataset, parser.batch_chunks)
    evaluator = ignite.engine.create_supervised_evaluator(container, metrics={
        'RMSE': torchani.ignite.RMSEMetric('energies')
    })
    evaluator.run(dataloader)
    metrics = evaluator.state.metrics
    rmse = hartree2kcal(metrics['RMSE'])
    print(rmse, 'kcal/mol')