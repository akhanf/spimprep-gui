import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
import re
import subprocess
import tempfile
import shutil
import threading
import git
from google.cloud import storage
import os
import io
import time
import sys
import gcsfs




class SPIMPrepApp:
    def __init__(self, root):
        self.root = root
        self.root.title("SPIMprep Configuration Tool")


        # Add a StringVar to hold the selection for execution method
        #self.execution_method = tk.StringVar(value="remote")  # Default is "coiled" remote


        self.temp_dir = None  # Initialize temp_dir to None
        self.global_settings_frame()
        self.dataset_info_frame()
        self.output_uri_frame()
        self.output_dir_frame()

        # Ensure cleanup is called when the window is closed
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    

    def global_settings_frame(self):
        frame = tk.LabelFrame(self.root, text="Global Settings")
        frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        # Global settings
        self.gcs_project = self.create_labeled_entry(frame, "GCS Project:", 0, default="t-system-193821")
        self.vm_type = self.create_labeled_entry(frame, "VM Type:", 1, default="c2d-highmem-56")
        self.cores = self.create_labeled_entry(frame, "Core per rule:", 2, default="56")
        self.memory_mb = self.create_labeled_entry(frame, "Memory (MB):", 3, default="440000")
        #self.vm_type = self.create_labeled_entry(frame, "VM Type:", 1, default="e2-standard-32")
        #self.cores = self.create_labeled_entry(frame, "Core per rule:", 2, default="32")
        #self.memory_mb = self.create_labeled_entry(frame, "Memory (MB):", 3, default="128000")

        self.disk_size = self.create_labeled_entry(frame, "Disk Size (GiB, default 0 will request 160% of dataset size):", 4, default="0")
        self.spimprep_repo = self.create_labeled_entry(frame, "SPIMprep Repo:", 5, default="https://github.com/khanlab/SPIMprep")
        self.spimprep_tag = self.create_labeled_entry(frame, "SPIMprep Tag:", 6, default="cloudinput")


    def dataset_info_frame(self):
        self.dataset_frame = tk.LabelFrame(self.root, text="Dataset Information")
        self.dataset_frame.grid(row=1, column=0, padx=10, pady=10, sticky="ew")

        self.subject = self.create_labeled_entry(self.dataset_frame, "Subject:", 0, regex="^[a-zA-Z0-9]+$")
        self.sample = self.create_labeled_entry(self.dataset_frame, "Sample:", 1, default="brain", regex="^[a-zA-Z0-9]+$")
        self.acq = self.create_labeled_entry(self.dataset_frame, "Acquisition (acq):", 2, default="blaze", regex="^[a-zA-Z0-9]+$")

        # Stain options
        self.stain_presets = ["autof", "abeta", "PI"]
        self.stains = []

        self.add_stain_row()

        tk.Button(self.dataset_frame, text="Add Stain", command=self.add_stain_row).grid(row=4, column=0, columnspan=3, pady=10)

        # Dataset path
        tk.Label(self.dataset_frame, text="Dataset Path:").grid(row=5, column=0, sticky="e")
        self.local_dataset_path = tk.Entry(self.dataset_frame, width=50)
        self.local_dataset_path.grid(row=5, column=1)
        tk.Button(self.dataset_frame, text="Browse", command=self.browse_dataset_path).grid(row=5, column=2)

    def output_uri_frame(self):
        frame = tk.LabelFrame(self.root, text="Cloud Execution")
        frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")

        self.out_bids_uri = self.create_labeled_entry(frame, "Output BIDS URI:", 0, default="gcs://khanlab-lightsheet/data/marmoset_pilot/bids")

        tk.Button(frame, text="Check URI", command=self.check_gcs_uri).grid(row=1, column=0, columnspan=3, pady=10)
        tk.Button(frame, text="Run SPIMprep cloud", command=self.run_spimprep_cloud).grid(row=2, column=0, columnspan=3, pady=10)

    def output_dir_frame(self):
        frame = tk.LabelFrame(self.root, text="Local Execution")
        frame.grid(row=3, column=0, padx=10, pady=10, sticky="ew")

        self.out_bids_dir = self.create_labeled_entry(frame, "Output BIDS directory:", 0, default="/cifs/trident/projects/marmoset_pilot/lightsheet/bids_20240820")
        self.out_work_dir = self.create_labeled_entry(frame, "Output Work directory:", 1, default="/cifs/trident/.temp_work_marmoset_pilot")

        tk.Button(frame, text="Run SPIMprep local", command=self.run_spimprep_local).grid(row=3, column=0, columnspan=3, pady=10)


    def execution_method_frame(self):
        frame = tk.LabelFrame(self.root, text="Execution Method")
        frame.grid(row=3, column=0, padx=10, pady=10, sticky="ew")

        tk.Radiobutton(frame, text="Remote (Coiled on Google Cloud)", variable=self.execution_method, value="coiled").grid(row=0, column=0, padx=5, pady=5)
        tk.Radiobutton(frame, text="Local (Singularity)", variable=self.execution_method, value="local").grid(row=0, column=1, padx=5, pady=5)


    def create_labeled_entry(self, parent, label_text, row, default="", regex=None):
        tk.Label(parent, text=label_text).grid(row=row, column=0, sticky="e")
        entry = tk.Entry(parent, width=50)
        entry.grid(row=row, column=1)
        entry.insert(0, default)
        if regex:
            entry.bind("<FocusOut>", lambda e: self.validate_entry(entry, regex))
        return entry

    def validate_entry(self, entry, regex):
        value = entry.get()
        if not re.match(regex, value):
            messagebox.showerror("Invalid Input", f"Invalid input: {value}")

    def add_stain_row(self):
        index = len(self.stains)
        label = f"Stain {index}:"
        stain_var = tk.StringVar(value=self.stain_presets[0])
        self.stains.append(stain_var)

        tk.Label(self.dataset_frame, text=label).grid(row=3+index, column=0, sticky="e")
        stain_menu = tk.OptionMenu(self.dataset_frame, stain_var, *self.stain_presets)
        stain_menu.grid(row=3+index, column=1, sticky="w")

    def browse_dataset_path(self):
        directory = filedialog.askdirectory()
        if directory:
            self.local_dataset_path.delete(0, tk.END)
            self.local_dataset_path.insert(0, directory)

    def check_gcs_uri(self):
        uri = self.out_bids_uri.get()
        try:
            client = storage.Client()
            bucket_name = uri.split('/')[2]
            bucket = client.get_bucket(bucket_name)
            test_blob = bucket.blob('test.txt')
            test_blob.upload_from_string('This is a test.')
            test_blob.delete()
            messagebox.showinfo("Success", "URI is writable.")
        except Exception as e:
            messagebox.showerror("Error", f"Cannot write to URI: {e}")

    def calc_gcs_folder_size(self,uri):

        fs = gcsfs.GCSFileSystem()

        # List all files under the given URI
        file_list = fs.ls(uri)

        total_size = 0
        for file in file_list:
            # Get the file info and add its size to the total
            file_info = fs.info(file)
            total_size += file_info['size']

        total_size_gib = total_size / (1024 ** 3)
        return total_size_gib

    def run_spimprep_cloud(self):
       
        self.temp_dir = tempfile.mkdtemp()  # Create a persistent temporary directory
        repo = self.spimprep_repo.get()
        tag = self.spimprep_tag.get()
        git.Repo.clone_from(repo, self.temp_dir, branch=tag)

        local_folder_name = Path(self.local_dataset_path.get()).name

        #create remote dataset path:
        remote_dataset_root = f"{self.out_bids_uri.get()}/sourcedata"
        remote_dataset_path = f"{remote_dataset_root}/{local_folder_name}"
        touch_path = f"{remote_dataset_path}/.transfer_completed"
        remote_dataset_root_gs = "gs"+remote_dataset_root[3:]  #replace gcs:// with gs:// for gcloud storage cp

        # Prepare datasets.tsv
        dataset_info = {
            "subject": self.subject.get(),
            "sample": self.sample.get(),
            "acq": self.acq.get(),
            "stain_0": self.stains[0].get(),
            "dataset_path": remote_dataset_path,
        }
        for i, stain_var in enumerate(self.stains[1:], start=1):
            dataset_info[f"stain_{i}"] = stain_var.get()

        datasets_tsv_path = os.path.join(self.temp_dir, 'config', 'datasets.tsv')
        with open(datasets_tsv_path, 'w') as f:
            headers = '\t'.join(dataset_info.keys())
            f.write(headers + '\n')
            values = '\t'.join(dataset_info.values())
            f.write(values + '\n')


        # Run the SPIMprep command
        memory_mb = self.memory_mb.get()
        cores = self.cores.get()
        gcs_project = self.gcs_project.get()
        vm_type = self.vm_type.get()
        out_bids_uri = self.out_bids_uri.get()
        disk_size = self.disk_size.get()



        # Run the gcloud storage cp command
        gcloud_cp_command = (
            f"gcloud storage cp --no-clobber --recursive {self.local_dataset_path.get()} {remote_dataset_root_gs}"
        )


        # first check if the completion touch-file exists:
        fs = gcsfs.GCSFileSystem()
        if not fs.exists(touch_path):
            # run the cp command first and touch the completion flag
            self.run_commands([gcloud_cp_command], self.temp_dir)
            with fs.open(touch_path, 'wb') as f:
                pass  
        

        # then calculate the size of the dataset if the requested size is 0
        if disk_size == 0:
            size_GiB=self.calc_gcs_folder_size(remote_dataset_path)
            disk_size = int(size_GiB * 1.6) #request disk 160% the size of the dataset (note if we optimize the importing in SPIMprep to go directly from bucket to zarr without copying first, then this can be much lower)


        snakemake_command = (
            f"snakemake -c all --set-resources bigstitcher:mem_mb={memory_mb} fuse_dataset:mem_mb={memory_mb} "
            f"--storage-gcs-project {gcs_project} --config root={out_bids_uri} cores_per_rule={cores} --show-failed-logs"
        )


        coiled_command = (
            f"coiled run --file config --file resources --file workflow --file qc --software spimprep-deps "
            f"--vm-type {vm_type} --disk-size {disk_size} --forward-gcp-adc \"{snakemake_command}\""
        )


         # Close the Tkinter window
        self.root.destroy()

        # Run the spimprep command
        
        self.run_commands([coiled_command], self.temp_dir)


    def run_spimprep_local(self):
       
        self.temp_dir = tempfile.mkdtemp()  # Create a persistent temporary directory
        
        
        repo = self.spimprep_repo.get()
        tag = self.spimprep_tag.get()
        git.Repo.clone_from(repo, self.temp_dir, branch=tag)


        # Prepare datasets.tsv
        dataset_info = {
            "subject": self.subject.get(),
            "sample": self.sample.get(),
            "acq": self.acq.get(),
            "stain_0": self.stains[0].get(),
            "dataset_path": self.local_dataset_path.get(),
        }
        for i, stain_var in enumerate(self.stains[1:], start=1):
            dataset_info[f"stain_{i}"] = stain_var.get()

        datasets_tsv_path = os.path.join(self.temp_dir, 'config', 'datasets.tsv')
        with open(datasets_tsv_path, 'w') as f:
            headers = '\t'.join(dataset_info.keys())
            f.write(headers + '\n')
            values = '\t'.join(dataset_info.values())
            f.write(values + '\n')



        # Run the SPIMprep command
        memory_mb = self.memory_mb.get()
        cores = self.cores.get()
        gcs_project = self.gcs_project.get()
        out_bids_dir = self.out_bids_dir.get()
        out_work_dir = self.out_work_dir.get()


        snakemake_command = (
            f"snakemake -c all --set-resources bigstitcher:mem_mb={memory_mb} fuse_dataset:mem_mb={memory_mb} "
            f"--storage-gcs-project {gcs_project} --config root={out_bids_dir} cores_per_rule={cores} work={out_work_dir} --show-failed-logs"
        )


        singularity_command = (
            f"singularity exec -e docker://khanlab/spimprep-deps:main {snakemake_command}"
        )


         # Close the Tkinter window
        self.root.destroy()

        # Run the spimprep command
        
        self.run_commands([singularity_command], self.temp_dir)




    def run_commands(self, commands, working_dir):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "process_output.log")

            for command in commands:
                # Echo the command being run
                print(f"\nRunning command: {command}\n")

                with io.open(log_file, "w") as writer, io.open(log_file, "r", 1) as reader:
                    process = subprocess.Popen(command, shell=True, cwd=working_dir, stdout=writer, stderr=subprocess.STDOUT, text=True)

                    # Continuously read from the log file and write to the terminal
                    while process.poll() is None:
                        output = reader.read()
                        if output:
                            sys.stdout.write(output)
                            sys.stdout.flush()
                        time.sleep(0.5)


                    # Ensure the remaining output is printed
                    remaining_output = reader.read()
                    if remaining_output:
                        sys.stdout.write(remaining_output)
                        sys.stdout.flush()



                # Check if the process finished successfully
                if process.returncode != 0:
                    print(f"Command failed with return code {process.returncode}")
                    break

            print("All commands have finished running.")



    def on_closing(self):
        self.cleanup()
        self.root.destroy()  # Close the window


    def cleanup(self):
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)



def main():
    root = tk.Tk()
    app = SPIMPrepApp(root)
    root.protocol("WM_DELETE_WINDOW", app.cleanup)  # Ensure cleanup on close
    root.mainloop()



if __name__ == "__main__":
    main()

