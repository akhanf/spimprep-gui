import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
import subprocess
import tempfile
import shutil
import io
import time
import sys
import os
import gcsfs
from datetime import datetime
from tinydb import TinyDB, Query
import re
import threading
import git
from google.cloud import storage
import os


class SPIMPrepApp:
    def __init__(self, root):
        self.root = root
        self.root.title("SPIMprep Configuration Tool")
        
        # Create or open the TinyDB database
        self.db = TinyDB('spimprep_jobs.json')

        self.temp_dir = None  # Initialize temp_dir to None
        self.global_settings_frame()
        self.sample_info_frame()
        self.output_uri_frame()
        self.output_dir_frame()

        # New Frame for Loading Previous Jobs
        self.previous_runs_frame()

        # Ensure cleanup is called when the window is closed
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def global_settings_frame(self):
        frame = tk.LabelFrame(self.root, text="Global Settings")
        frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        self.gcs_project = self.create_labeled_entry(frame, "GCS Project:", 0, default="t-system-193821")
        self.vm_type = self.create_labeled_entry(frame, "VM Type:", 1, default="c2d-highmem-16")
        self.cores = self.create_labeled_entry(frame, "Core per rule:", 2, default="16")
        self.memory_mb = self.create_labeled_entry(frame, "Memory (MB):", 3, default="128000")
        self.disk_size = self.create_labeled_entry(frame, "Disk Size (GiB, default 0 will request 160% of sample size):", 4, default="1500")
        self.spimprep_repo = self.create_labeled_entry(frame, "SPIMprep Repo:", 5, default="https://github.com/khanlab/SPIMprep")
        self.spimprep_tag = self.create_labeled_entry(frame, "SPIMprep Tag:", 6, default="main")

    def sample_info_frame(self):
        self.sample_frame = tk.LabelFrame(self.root, text="Sample Information")
        self.sample_frame.grid(row=1, column=0, padx=10, pady=10, sticky="ew")

        self.subject = self.create_labeled_entry(self.sample_frame, "Subject:", 0, regex="^[a-zA-Z0-9]+$")
        self.sample = self.create_labeled_entry(self.sample_frame, "Sample:", 1, default="brain", regex="^[a-zA-Z0-9]+$")
        self.acq = self.create_labeled_entry(self.sample_frame, "Acquisition (acq):", 2, default="blaze", regex="^[a-zA-Z0-9]+$")

        self.stain_presets = ["n/a","AutoF", "Abeta", "PI", "AlphaSynuclein", "GFAP", "Gq", "Lectin", "Iba1", "undefined0", "undefined1", "undefined2"]
        self.stains = []
        self.add_stain_row()
        self.add_stain_row()
        self.add_stain_row()
        tk.Button(self.sample_frame, text="Add Channel", command=self.add_stain_row).grid(row=4, column=0, columnspan=3, pady=10)

        # Sample path
        tk.Label(self.sample_frame, text="Sample Path:").grid(row=8, column=0, sticky="e")
        self.local_sample_path = tk.Entry(self.sample_frame, width=50)
        self.local_sample_path.grid(row=8, column=1)
        tk.Button(self.sample_frame, text="Browse", command=self.browse_sample_path).grid(row=8, column=2)

    def output_uri_frame(self):
        frame = tk.LabelFrame(self.root, text="Cloud Execution")
        frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")

        self.out_bids_uri = self.create_labeled_entry(frame, "Output BIDS URI:", 0, default="gcs://khanlab-lightsheet/data/marmoset_pilot/bids")
        tk.Button(frame, text="Check URI", command=self.check_gcs_uri).grid(row=1, column=0, columnspan=3, pady=10)
        tk.Button(frame, text="Run SPIMprep cloud", command=self.run_spimprep_cloud).grid(row=2, column=0, columnspan=3, pady=10)

    def output_dir_frame(self):
        frame = tk.LabelFrame(self.root, text="Local Execution")
        frame.grid(row=3, column=0, padx=10, pady=10, sticky="ew")

        self.out_bids_dir = self.create_labeled_entry(frame, "Output BIDS directory:", 0, default="/cifs/trident/projects/NAME_OF_PROJECT/lightsheet/bids")
        self.out_work_dir = self.create_labeled_entry(frame, "Output Work directory:", 1, default="/cifs/trident/.work/NAME_OF_PROJECT")
        tk.Button(frame, text="Run SPIMprep local", command=self.run_spimprep_local).grid(row=3, column=0, columnspan=3, pady=10)

    def previous_runs_frame(self):
        """ Frame to load and resubmit previous runs """
        frame = tk.LabelFrame(self.root, text="Previous Runs")
        frame.grid(row=4, column=0, padx=10, pady=10, sticky="ew")

        # Dropdown for previous runs
        tk.Label(frame, text="Select Previous Run:").grid(row=0, column=0, sticky="e")
        self.previous_run_var = tk.StringVar(frame)

        # Initialize the OptionMenu but with an empty list initially
        self.previous_run_menu = tk.OptionMenu(frame, self.previous_run_var, "")
        self.previous_run_menu.grid(row=0, column=1)

        # Populate the dropdown after initializing the menu
        self.populate_previous_runs_dropdown()

        # Button to load the selected run
        tk.Button(frame, text="Load Run", command=self.load_previous_run).grid(row=1, column=0, columnspan=2, pady=10)

    def populate_previous_runs_dropdown(self):
        """ Refresh dropdown menu options from the database """
        menu = self.previous_run_menu["menu"]
        menu.delete(0, "end")
        for run in self.get_previous_runs():
            menu.add_command(label=run, command=lambda value=run: self.previous_run_var.set(value))


    def get_previous_runs(self):
        """ Return a list of previous run identifiers (e.g., timestamp or job_id) """
        return [str(job['job_id']) + " - " + job['subject'] for job in self.db.all()]

    def load_previous_run(self):
        """ Load a previous run's parameters into the UI """
        job_id = int(self.previous_run_var.get().split(" ")[0])  # Get the job_id from the selected run
        job_query = Query()
        result = self.db.search(job_query.job_id == job_id)

        if result:
            job_data = result[0]
            self.subject.delete(0, tk.END)
            self.subject.insert(0, job_data['subject'])

            self.sample.delete(0, tk.END)
            self.sample.insert(0, job_data['sample'])

            self.acq.delete(0, tk.END)
            self.acq.insert(0, job_data['acq'])

            self.local_sample_path.delete(0, tk.END)
            self.local_sample_path.insert(0, job_data['sample_path'])

            for i, stain_var in enumerate(self.stains):
                stain_var.set(job_data.get(f'stain_{i}', ''))

    def add_submission_to_db(self):
        """ Add the current submission to the TinyDB database """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        job_id = len(self.db) + 1  # Simple job_id increment

        submission = {
            'job_id': job_id,
            'timestamp': timestamp,
            'subject': self.subject.get(),
            'sample': self.sample.get(),
            'acq': self.acq.get(),
            'sample_path': self.local_sample_path.get(),
            'processing_parameters': {
                'memory_mb': self.memory_mb.get(),
                'cores': self.cores.get(),
                'vm_type': self.vm_type.get()
            }
        }

        for i, stain_var in enumerate(self.stains):
            submission[f'stain_{i}'] = stain_var.get()

        self.db.insert(submission)
        self.populate_previous_runs_dropdown()  # Update dropdown after new submission



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

        tk.Label(self.sample_frame, text=label).grid(row=3+index, column=0, sticky="e")
        stain_menu = tk.OptionMenu(self.sample_frame, stain_var, *self.stain_presets)
        stain_menu.grid(row=3+index, column=1, sticky="w")

    def browse_sample_path(self):
        directory = filedialog.askdirectory()
        if directory:
            self.local_sample_path.delete(0, tk.END)
            self.local_sample_path.insert(0, directory)

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
       
        self.add_submission_to_db()


        self.temp_dir = tempfile.mkdtemp()  # Create a persistent temporary directory
        repo = self.spimprep_repo.get()
        tag = self.spimprep_tag.get()
        git.Repo.clone_from(repo, self.temp_dir, branch=tag)

        local_folder_name = Path(self.local_sample_path.get()).name

        #create remote sample path:
        remote_bids_root = f"{self.out_bids_uri.get()}/sourcedata"
        remote_sample_path = f"{remote_bids_root}/{local_folder_name}"
        touch_path = f"{remote_sample_path}/.transfer_completed"
        remote_sample_path_gs = "gs"+remote_sample_path[3:]  #replace gcs:// with gs:// for gcloud storage cp

        # Prepare samples.tsv
        sample_info = {
            "subject": self.subject.get(),
            "sample": self.sample.get(),
            "acq": self.acq.get(),
            "stain_0": self.stains[0].get(),
            "sample_path": remote_sample_path,
        }
        for i, stain_var in enumerate(self.stains[1:], start=1):
            sample_info[f"stain_{i}"] = stain_var.get()

        samples_tsv_path = os.path.join(self.temp_dir, 'config', 'samples.tsv')
        with open(samples_tsv_path, 'w') as f:
            headers = '\t'.join(sample_info.keys())
            f.write(headers + '\n')
            values = '\t'.join(sample_info.values())
            f.write(values + '\n')

    

        # Run the SPIMprep command
        memory_mb = self.memory_mb.get()
        cores = self.cores.get()
        gcs_project = self.gcs_project.get()
        vm_type = self.vm_type.get()
        out_bids_uri = self.out_bids_uri.get()
        disk_size = self.disk_size.get()



        # Run the gcloud storage cp command
        exclude=r'".*\\.ims$|.*\\.mp4$"'
        gcloud_cp_command = (
            f"gcloud storage rsync  --recursive --exclude={exclude} {self.local_sample_path.get()} {remote_sample_path_gs}"
        )
        print(gcloud_cp_command)

        # first check if the completion touch-file exists:
        fs = gcsfs.GCSFileSystem()
        if not fs.exists(touch_path):
            # run the cp command first and touch the completion flag
            self.run_commands([gcloud_cp_command], self.temp_dir)
            with fs.open(touch_path, 'wb') as f:
                pass  
        

        # then calculate the size of the sample if the requested size is 0
        if disk_size == 0:
            size_GiB=self.calc_gcs_folder_size(remote_sample_path)
            disk_size = int(size_GiB * 1.6) #request disk 160% the size of the sample (note if we optimize the importing in SPIMprep to go directly from bucket to zarr without copying first, then this can be much lower)


        snakemake_command = (
            f"snakemake -c all  "
            f"--storage-gcs-project {gcs_project} --config root={out_bids_uri} total_cores={cores} total_mem_mb={memory_mb} --show-failed-logs"
        )


        coiled_command = (
            f"coiled run --file config --file resources --file workflow --software spimprep-deps "
            f"--tag bids_dir={out_bids_uri} --tag subject={self.subject.get()} "
            f"--vm-type {vm_type} --disk-size {disk_size} --forward-gcp-adc \"{snakemake_command}\""
        )


         # Close the Tkinter window
        self.root.destroy()

        # Run the spimprep command
        
        self.run_commands([coiled_command], self.temp_dir)


    def run_spimprep_local(self):
       
        self.add_submission_to_db()

        self.temp_dir = tempfile.mkdtemp()  # Create a persistent temporary directory
        
        
        repo = self.spimprep_repo.get()
        tag = self.spimprep_tag.get()
        git.Repo.clone_from(repo, self.temp_dir, branch=tag)


        # Prepare samples.tsv
        sample_info = {
            "subject": self.subject.get(),
            "sample": self.sample.get(),
            "acq": self.acq.get(),
            "stain_0": self.stains[0].get(),
            "sample_path": self.local_sample_path.get(),
        }
        for i, stain_var in enumerate(self.stains[1:], start=1):
            sample_info[f"stain_{i}"] = stain_var.get()

        samples_tsv_path = os.path.join(self.temp_dir, 'config', 'samples.tsv')
        with open(samples_tsv_path, 'w') as f:
            headers = '\t'.join(sample_info.keys())
            f.write(headers + '\n')
            values = '\t'.join(sample_info.values())
            f.write(values + '\n')



        # Run the SPIMprep command
        memory_mb = self.memory_mb.get()
        cores = self.cores.get()
        gcs_project = self.gcs_project.get()
        out_bids_dir = self.out_bids_dir.get()
        out_work_dir = self.out_work_dir.get()


        snakemake_command = (
            f"snakemake -c all "
            f"--storage-gcs-project {gcs_project} --config root={out_bids_dir} total_cores={cores} total_mem_mb={memory_mb} work={out_work_dir} --show-failed-logs"
        )


        singularity_command = (
            f"singularity exec -e docker://khanlab/spimprep-deps:v0.1.0 {snakemake_command}"
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

