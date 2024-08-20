import tkinter as tk
from tkinter import filedialog, messagebox
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


class SPIMPrepApp:
    def __init__(self, root):
        self.root = root
        self.root.title("SPIMprep Configuration Tool")

        self.temp_dir = None  # Initialize temp_dir to None
        self.global_settings_frame()
        self.dataset_info_frame()
        self.output_uri_frame()

        # Ensure cleanup is called when the window is closed
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    

    def global_settings_frame(self):
        frame = tk.LabelFrame(self.root, text="Global Settings")
        frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        # Global settings
        self.gcs_project = self.create_labeled_entry(frame, "GCS Project:", 0, default="t-system-193821")
        self.vm_type = self.create_labeled_entry(frame, "VM Type:", 1, default="e2-standard-32")
        self.memory_mb = self.create_labeled_entry(frame, "Memory (MB):", 2, default="128000")
        self.spimprep_repo = self.create_labeled_entry(frame, "SPIMprep Repo:", 3, default="https://github.com/khanlab/SPIMprep")
        self.spimprep_tag = self.create_labeled_entry(frame, "SPIMprep Tag:", 4, default="cloudinput")

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
        frame = tk.LabelFrame(self.root, text="Output Settings")
        frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")

        self.out_bids_uri = self.create_labeled_entry(frame, "Output BIDS URI:", 0, default="gcs://khanlab-lightsheet/data/marmoset_pilot/bids")

        tk.Button(frame, text="Check URI", command=self.check_gcs_uri).grid(row=1, column=0, columnspan=3, pady=10)
        tk.Button(frame, text="Run SPIMprep", command=self.run_spimprep).grid(row=2, column=0, columnspan=3, pady=10)

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


    def run_spimprep(self):
        self.temp_dir = tempfile.mkdtemp()  # Create a persistent temporary directory
        repo = self.spimprep_repo.get()
        tag = self.spimprep_tag.get()
        git.Repo.clone_from(repo, self.temp_dir, branch=tag)

        #create remote dataset path:
        remote_dataset_path = f"{self.out_bids_uri.get()}/sourcedata/{self.subject.get()}_{self.sample.get()}_{self.acq.get()}"
        remote_dataset_path_gs = "gs"+remote_dataset_path[3:]  #replace gcs:// with gs:// for gcloud storage cp


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


        # Run the gcloud storage cp command
        gcloud_cp_command = (
            f"gcloud storage cp --no-clobber --recursive {self.local_dataset_path.get()} {remote_dataset_path_gs}"
        )


        # Run the SPIMprep command
        memory_mb = self.memory_mb.get()
        gcs_project = self.gcs_project.get()
        vm_type = self.vm_type.get()
        out_bids_uri = self.out_bids_uri.get()

        spimprep_command = (
            f"coiled run --file config --file resources --file workflow --file qc --software spimprep-deps "
            f"\"snakemake -c all --set-resources bigstitcher:mem_mb={memory_mb} fuse_dataset:mem_mb={memory_mb} "
            f"--storage-gcs-project {gcs_project} --config root={out_bids_uri}\" --vm-type {vm_type} --forward-gcp-adc"
        )



        # Chain the commands and run them
        self.run_commands([gcloud_cp_command, spimprep_command], self.temp_dir)




    def run_commands(self, commands, working_dir):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "process_output.log")

            for command in commands:
                # Echo the command being run
                print(f"\nRunning command: {command}\n")

                with io.open(log_file, "wb") as writer, io.open(log_file, "rb", 1) as reader:
                    process = subprocess.Popen(command, shell=True, cwd=working_dir, stdout=writer, stderr=subprocess.STDOUT)

                    # Continuously read from the log file and write to the terminal
                    while process.poll() is None:
                        sys.stdout.write(reader.read().decode())
                        sys.stdout.flush()
                        time.sleep(0.5)

                    # Ensure the remaining output is printed
                    sys.stdout.write(reader.read().decode())
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

