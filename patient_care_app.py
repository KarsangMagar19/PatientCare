import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkcalendar import DateEntry
import sqlite3
from datetime import datetime, timedelta
import re
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import traceback
import sys
import os
import platform
import shutil
import json
from zipfile import ZipFile

# --- Database Setup ---
def get_db_path():
    """Get a persistent database path that works for both development and compiled versions"""
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        if platform.system() == 'Windows':
            app_data = os.getenv('APPDATA')
            db_dir = os.path.join(app_data, 'PatientCare')
        else:
            db_dir = os.path.expanduser('~/.patientcare')
    else:
        # Running as script
        db_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Create directory if it doesn't exist
    os.makedirs(db_dir, exist_ok=True)
    
    return os.path.join(db_dir, 'patientcare.db')

def setup_database():
    try:
        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Enable foreign key constraints
        cursor.execute("PRAGMA foreign_keys = ON")
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Patients (
            PatientID INTEGER PRIMARY KEY AUTOINCREMENT,
            Name TEXT NOT NULL,
            Age INTEGER,
            Gender TEXT,
            Address TEXT,
            MobileNumber TEXT,
            EntryDate TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Medicines (
            MedicineID INTEGER PRIMARY KEY AUTOINCREMENT,
            PatientID INTEGER,
            MedicineName TEXT,
            StartDate TEXT,
            Quantity INTEGER,
            Frequency TEXT,
            EndDate TEXT,
            FOREIGN KEY(PatientID) REFERENCES Patients(PatientID) ON DELETE CASCADE
        )
        """)
        conn.commit()
        return conn, cursor
    except sqlite3.Error as e:
        messagebox.showerror("Database Error", f"Failed to setup database:\n{str(e)}")
        sys.exit(1)

# Initialize database connection
try:
    conn, cursor = setup_database()
except Exception as e:
    messagebox.showerror("Critical Error", f"Application cannot start:\n{str(e)}")
    sys.exit(1)

# --- Backup/Restore Functions ---
def backup_data():
    """Create a backup of the database and configuration"""
    try:
        db_path = get_db_path()
        backup_dir = os.path.join(os.path.dirname(db_path), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        
        # Create timestamped backup filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(backup_dir, f"patientcare_backup_{timestamp}.zip")
        
        # Create a zip file with database and metadata
        with ZipFile(backup_file, 'w') as zipf:
            zipf.write(db_path, os.path.basename(db_path))
            
            # Add metadata about the backup
            metadata = {
                "backup_date": timestamp,
                "database_version": "1.0",
                "records": {
                    "patients": cursor.execute("SELECT COUNT(*) FROM Patients").fetchone()[0],
                    "medicines": cursor.execute("SELECT COUNT(*) FROM Medicines").fetchone()[0]
                }
            }
            
            # Write metadata to a temporary file
            meta_file = os.path.join(backup_dir, "backup_meta.json")
            with open(meta_file, 'w') as f:
                json.dump(metadata, f)
            
            zipf.write(meta_file, "backup_meta.json")
            os.remove(meta_file)
        
        messagebox.showinfo("Backup Successful", 
                          f"Database backup created successfully at:\n{backup_file}\n"
                          f"Patients: {metadata['records']['patients']}\n"
                          f"Medicines: {metadata['records']['medicines']}")
        return True
    except Exception as e:
        messagebox.showerror("Backup Failed", f"Failed to create backup:\n{str(e)}")
        traceback.print_exc()
        return False

def restore_data():
    """Restore database from a backup file"""
    try:
        # Ask user to select backup file
        backup_file = filedialog.askopenfilename(
            title="Select Backup File",
            filetypes=[("ZIP Backup Files", "*.zip"), ("All Files", "*.*")]
        )
        
        if not backup_file:
            return False
            
        # Verify backup file
        if not os.path.exists(backup_file):
            messagebox.showerror("Error", "Selected backup file does not exist")
            return False
            
        # Confirm restore action
        if not messagebox.askyesno(
            "Confirm Restore",
            "WARNING: This will overwrite your current database.\n"
            "Are you sure you want to continue?"
        ):
            return False
            
        # Create temporary restore directory
        restore_dir = os.path.join(os.path.dirname(get_db_path())), "restore_temp"
        os.makedirs(restore_dir, exist_ok=True)
        
        try:
            # Extract backup
            with ZipFile(backup_file, 'r') as zipf:
                zipf.extractall(restore_dir)
                
            # Verify extracted files
            db_file = os.path.join(restore_dir, os.path.basename(get_db_path()))
            meta_file = os.path.join(restore_dir, "backup_meta.json")
            
            if not os.path.exists(db_file):
                raise Exception("Database file not found in backup")
                
            # Read metadata
            with open(meta_file, 'r') as f:
                metadata = json.load(f)
                
            # Close current database connection
            global conn, cursor
            conn.close()
            
            # Replace current database with backup
            shutil.copyfile(db_file, get_db_path())
            
            # Reopen database connection
            conn = sqlite3.connect(get_db_path())
            cursor = conn.cursor()
            
            messagebox.showinfo("Restore Successful", 
                              f"Database restored successfully from backup:\n{backup_file}\n"
                              f"Backup Date: {metadata['backup_date']}\n"
                              f"Patients: {metadata['records']['patients']}\n"
                              f"Medicines: {metadata['records']['medicines']}")
            return True
        finally:
            # Clean up temporary files
            try:
                shutil.rmtree(restore_dir)
            except:
                pass
    except Exception as e:
        messagebox.showerror("Restore Failed", f"Failed to restore backup:\n{str(e)}")
        traceback.print_exc()
        
        # Try to reconnect to original database
        try:
            conn = sqlite3.connect(get_db_path())
            cursor = conn.cursor()
        except:
            pass
            
        return False

# --- Helper Functions ---
def validate_mobile_number(mobile_number):
    if not mobile_number:  # Mobile number is optional
        return True
    try:
        return bool(re.match(r'^\d{10}$', mobile_number))
    except Exception:
        return False

def frequency_to_daily_count(freq):
    try:
        return {'OD': 1, 'BD': 2, 'TDS': 3, 'QID': 4}.get(freq.upper(), 1)
    except Exception:
        return 1

def calculate_remaining_tablets(start, end, qty, freq):
    try:
        daily = frequency_to_daily_count(freq)
        today = datetime.today().date()
        try:
            start = datetime.strptime(start, "%Y-%m-%d").date()
            end = datetime.strptime(end, "%Y-%m-%d").date()
        except:
            return 0
        if today > end:
            return 0
        taken = max((today - start).days, 0) * daily
        return max(qty - taken, 0)
    except Exception:
        return 0

def calculate_end_date(start_date, qty, freq):
    try:
        daily = frequency_to_daily_count(freq)
        if daily == 0:
            daily = 1
        days_needed = (qty + daily - 1) // daily
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
        except Exception:
            return start_date
        end = start + timedelta(days=days_needed - 1)
        return end.strftime("%Y-%m-%d")
    except Exception:
        return start_date

def get_next_available_patient_id():
    """Find the first available patient ID in sequence"""
    try:
        cursor.execute("SELECT PatientID FROM Patients ORDER BY PatientID")
        existing_ids = {row[0] for row in cursor.fetchall()}
        
        # Find the first missing ID starting from 1
        for candidate_id in range(1, max(existing_ids or [0]) + 2):
            if candidate_id not in existing_ids:
                return candidate_id
        return 1  # Fallback if no patients exist
    except Exception as e:
        messagebox.showerror("Database Error", f"Failed to get next patient ID:\n{str(e)}")
        return None

def resequence_patient_ids():
    try:
        cursor.execute("SELECT PatientID FROM Patients ORDER BY PatientID")
        ids = [row[0] for row in cursor.fetchall()]
        if not ids:
            return

        mapping = {old_id: new_id+1 for new_id, old_id in enumerate(ids)}
        
        try:
            cursor.execute("PRAGMA foreign_keys=OFF")
            conn.commit()
            
            # Create temporary table and copy data
            cursor.execute("CREATE TABLE IF NOT EXISTS Patients_temp AS SELECT * FROM Patients")
            cursor.execute("DELETE FROM Patients")
            
            # Reinsert with new IDs
            for old_id in ids:
                cursor.execute("SELECT Name, Age, Gender, Address, MobileNumber FROM Patients_temp WHERE PatientID=?", (old_id,))
                data = cursor.fetchone()
                if data:
                    cursor.execute("""
                        INSERT INTO Patients (PatientID, Name, Age, Gender, Address, MobileNumber) 
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (mapping[old_id], *data))
            
            # Update medicine references
            for old_id, new_id in mapping.items():
                cursor.execute("UPDATE Medicines SET PatientID=? WHERE PatientID=?", (new_id, old_id))
            
            # Clean up
            cursor.execute("DROP TABLE Patients_temp")
            conn.commit()
            cursor.execute("PRAGMA foreign_keys=ON")
            conn.commit()
            
        except sqlite3.Error as e:
            conn.rollback()
            cursor.execute("PRAGMA foreign_keys=ON")
            raise e
            
    except Exception as e:
        messagebox.showerror("Database Error", f"Failed to resequence patient IDs:\n{str(e)}")
        traceback.print_exc()

# --- Marquee Widget ---
class Marquee(tk.Canvas):
    def __init__(self, parent, text, **kwargs):
        try:
            super().__init__(parent, **kwargs)
            self.text = text
            self.text_id = self.create_text(0, -2000, text=self.text, font=("Arial", 16))
            self.pack()
            self.after(100, self.scroll_text)
        except Exception as e:
            messagebox.showerror("UI Error", f"Failed to create marquee:\n{str(e)}")
            raise

    def scroll_text(self):
        try:
            self.move(self.text_id, -2, 0)
            x1, y1, x2, y2 = self.bbox(self.text_id)
            if x2 < 0:
                width = self.winfo_width()
                self.coords(self.text_id, width, y1)
            self.after(50, self.scroll_text)
        except Exception:
            pass  # Silently fail if widget is destroyed

# --- Main App ---
class PatientCareApp:
    def __init__(self, root):
        self.root = root
        try:
            self.root.title("Patient Care Manager")
            self.root.geometry("1150x750")
            self.editing_id = None
            self.setup_ui()
            self.load()
        except Exception as e:
            messagebox.showerror("Initialization Error", f"Failed to initialize application:\n{str(e)}")
            traceback.print_exc()
            self.root.destroy()

    def setup_ui(self):
        try:
            # Header
            ttk.Label(self.root, text="APPU MEDI SUPPLIERS", font=("Arial", 24)).pack(pady=10)

            # Patient Info Frame
            p_frame = ttk.LabelFrame(self.root, text="Patient Information")
            p_frame.pack(fill="x", padx=10, pady=5)

            # Patient Info Fields
            ttk.Label(p_frame, text="Name:").grid(row=0, column=0, padx=5, sticky="e")
            self.name = ttk.Entry(p_frame, width=20)
            self.name.grid(row=0, column=1)

            ttk.Label(p_frame, text="Age:").grid(row=0, column=2, padx=5, sticky="e")
            self.age = ttk.Entry(p_frame, width=5)
            self.age.grid(row=0, column=3)

            ttk.Label(p_frame, text="Gender:").grid(row=0, column=4, padx=5, sticky="e")
            self.gender = ttk.Combobox(p_frame, values=["Male", "Female", "Other"], width=10)
            self.gender.grid(row=0, column=5)

            ttk.Label(p_frame, text="Mobile Number:").grid(row=1, column=0, padx=5, sticky="e")
            self.mobile = ttk.Entry(p_frame, width=15)
            self.mobile.grid(row=1, column=1)

            ttk.Label(p_frame, text="Address:").grid(row=1, column=2, padx=5, sticky="e")
            self.address = ttk.Entry(p_frame, width=30)
            self.address.grid(row=1, column=3, columnspan=3, sticky="w")

            # Medicine Info Frame
            self.m_frame = ttk.LabelFrame(self.root, text="Medicine Details")
            self.m_frame.pack(fill="x", padx=10, pady=5)

            # Medicine Headers
            headings = ["Name", "Start", "Qty(tab)", "Freq", "End", "❌"]
            for i, head in enumerate(headings):
                ttk.Label(self.m_frame, text=head).grid(row=0, column=i)

            self.meds = []
            self.add_medicine_row()

            # Buttons Frame
            btns = ttk.Frame(self.root)
            btns.pack(pady=5)

            # Action Buttons
            ttk.Button(btns, text="Add Medicine", command=self.add_medicine_row).grid(row=0, column=0, padx=5)
            ttk.Button(btns, text="Save", command=self.save).grid(row=0, column=1, padx=5)
            ttk.Button(btns, text="Update", command=self.update).grid(row=0, column=2, padx=5)
            ttk.Button(btns, text="Delete", command=self.delete).grid(row=0, column=3, padx=5)
            ttk.Button(btns, text="Load", command=self.load).grid(row=0, column=4, padx=5)
            ttk.Button(btns, text="Export PDF", command=self.export_pdf).grid(row=0, column=5, padx=5)
            
            # Backup/Restore Buttons (new)
            backup_frame = ttk.Frame(self.root)
            backup_frame.pack(fill="x", padx=10, pady=5)
            
            ttk.Button(backup_frame, text="Backup Data", command=backup_data).pack(side="left", padx=5)
            ttk.Button(backup_frame, text="Restore Data", command=restore_data).pack(side="left", padx=5)

            # Marquee Frame
            marquee_frame = ttk.Frame(self.root)
            marquee_frame.pack(fill="x", padx=10)
            self.marquee = Marquee(marquee_frame, text="  ALL PATIENT'S DATA  ", height=30, bg="white")
            self.marquee.pack(fill="x")

            # Table Header Frame
            table_header_frame = ttk.Frame(self.root)
            table_header_frame.pack(fill="x", padx=10, pady=(10, 0))
            
            # "All Patient's Data" label in bold
            ttk.Label(table_header_frame, text="All Patient's Data", font=("Arial", 12, "bold")).pack(side="left", padx=5)
            
            # Search Frame (moved to be next to the table header)
            search_frame = ttk.Frame(table_header_frame)
            search_frame.pack(side="right", padx=5)
            
            ttk.Label(search_frame, text="Search:").pack(side="left", padx=5)
            self.search_var = tk.StringVar()
            search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=30)
            search_entry.pack(side="left", padx=5)
            search_entry.bind("<KeyRelease>", self.search_patients)
            
            ttk.Button(search_frame, text="Clear", command=self.clear_search).pack(side="left", padx=5)

            # Treeview with Scrollbars
            cols = ("PatientID", "Name", "Age", "Gender", "Address", "Mobile", "Medicine", "Start", "Qty(tab)", "Freq", "End", "Remaining")
            tree_frame = ttk.Frame(self.root)
            tree_frame.pack(fill="both", expand=True, padx=10, pady=5)

            self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings")
            for col in cols:
                self.tree.heading(col, text=col)
                self.tree.column(col, width=100, anchor="center")
            self.tree.pack(side="left", fill="both", expand=True)

            # Vertical scrollbar
            vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
            vsb.pack(side="right", fill="y")
            self.tree.configure(yscrollcommand=vsb.set)

            # Horizontal scrollbar
            hsb = ttk.Scrollbar(self.root, orient="horizontal", command=self.tree.xview)
            hsb.pack(fill="x", padx=10)
            self.tree.configure(xscrollcommand=hsb.set)

            # Bind double click to select record
            self.tree.bind("<Double-1>", self.select_record)

            # Tag colors for treeview
            self.tree.tag_configure("yellow", background="#e9cf28")
            self.tree.tag_configure("red", background="#e61628")

        except Exception as e:
            messagebox.showerror("UI Setup Error", f"Failed to setup user interface:\n{str(e)}")
            traceback.print_exc()
            raise

    def search_patients(self, event=None):
        search_term = self.search_var.get().strip().lower()
        if not search_term:
            self.load()
            return
            
        for row in self.tree.get_children():
            self.tree.delete(row)
            
        cursor.execute("""
            SELECT P.PatientID, P.Name, P.Age, P.Gender, P.Address, P.MobileNumber, 
                   M.MedicineName, M.StartDate, M.Quantity, M.Frequency, M.EndDate
            FROM Patients P
            LEFT JOIN Medicines M ON P.PatientID = M.PatientID
            WHERE LOWER(P.Name) LIKE ?
            ORDER BY P.PatientID
        """, (f"%{search_term}%",))
        
        rows = cursor.fetchall()
        self.populate_treeview(rows)

    def clear_search(self):
        self.search_var.set("")
        self.load()

    def populate_treeview(self, rows):
        for row in rows:
            try:
                patient_id, name, age, gender, address, mobile, medname, start, qty, freq, end = row
                qty = qty if qty is not None else 0
                freq = freq if freq else ""
                end = end if end else ""
                remaining = calculate_remaining_tablets(start, end, qty, freq) if medname else 0
                
                values = (
                    patient_id, name, age, gender, address, mobile, 
                    medname or "", start or "", qty, freq, end, remaining
                )

                # Apply color tags based on remaining tablets
                tag = ""
                if remaining <= 3:
                    tag = "red"
                elif remaining > 3 and remaining <= 5:
                    tag = "yellow"

                tags = (tag,) if tag else ()
                self.tree.insert("", tk.END, values=values, tags=tags)
                
            except Exception as e:
                messagebox.showerror("Load Error", f"Failed to load row {row}:\n{str(e)}")
                continue

    def add_medicine_row(self):
        try:
            row = len(self.meds) + 1
            med = {}

            # Medicine name entry
            med['name'] = ttk.Entry(self.m_frame, width=20)
            med['name'].grid(row=row, column=0)

            # Start date picker
            med['start'] = DateEntry(self.m_frame, width=12, date_pattern="yyyy-mm-dd")
            med['start'].grid(row=row, column=1)

            # Quantity entry
            med['qty'] = ttk.Entry(self.m_frame, width=5)
            med['qty'].grid(row=row, column=2)

            # Frequency combobox
            med['freq'] = ttk.Combobox(self.m_frame, values=["OD", "BD", "TDS", "QID"], width=5)
            med['freq'].grid(row=row, column=3)

            # End date picker (readonly)
            med['end'] = DateEntry(self.m_frame, width=12, date_pattern="yyyy-mm-dd")
            med['end'].grid(row=row, column=4)
            med['end'].config(state="readonly")

            # Delete button for this medicine row
            btn = ttk.Button(self.m_frame, text="❌", command=lambda: self.remove_medicine_row(med))
            btn.grid(row=row, column=5)

            med['btn'] = btn
            self.meds.append(med)

            # Bind auto-update events
            med['qty'].bind("<KeyRelease>", lambda e, m=med: self.auto_update_end_date(m))
            med['freq'].bind("<<ComboboxSelected>>", lambda e, m=med: self.auto_update_end_date(m))
            med['start'].bind("<<DateEntrySelected>>", lambda e, m=med: self.auto_update_end_date(m))

        except Exception as e:
            messagebox.showerror("Add Medicine Error", f"Failed to add medicine row:\n{str(e)}")
            traceback.print_exc()

    def auto_update_end_date(self, med):
        try:
            start_date = med['start'].get_date().strftime("%Y-%m-%d")
        except Exception:
            return

        try:
            qty_text = med['qty'].get()
            freq = med['freq'].get().strip().upper()
            
            if not qty_text.isdigit():
                return
                
            qty = int(qty_text)
            if freq not in ["OD", "BD", "TDS", "QID"]:
                return
                
            end_date = calculate_end_date(start_date, qty, freq)
            
            med['end'].config(state="normal")
            med['end'].set_date(end_date)
            med['end'].config(state="readonly")
            
        except Exception as e:
            messagebox.showerror("Auto Update Error", f"Failed to auto-update end date:\n{str(e)}")
            traceback.print_exc()

    def remove_medicine_row(self, med):
        try:
            for widget in med.values():
                if isinstance(widget, (ttk.Entry, ttk.Combobox, DateEntry, ttk.Button)):
                    widget.grid_forget()
                    widget.destroy()
            if med in self.meds:
                self.meds.remove(med)
        except Exception as e:
            messagebox.showerror("Remove Medicine Error", f"Failed to remove medicine row:\n{str(e)}")
            traceback.print_exc()

    def clear_form(self):
        try:
            self.name.delete(0, tk.END)
            self.age.delete(0, tk.END)
            self.gender.set('')
            self.address.delete(0, tk.END)
            self.mobile.delete(0, tk.END)
            for med in self.meds[:]:
                self.remove_medicine_row(med)
            self.add_medicine_row()
            self.editing_id = None
        except Exception as e:
            messagebox.showerror("Clear Form Error", f"Failed to clear form:\n{str(e)}")
            traceback.print_exc()

    def save(self):
        try:
            # Get and validate patient data
            name = self.name.get().strip().title()
            age = self.age.get().strip()
            gender = self.gender.get().strip()
            address = self.address.get().strip()
            mobile = self.mobile.get().strip()

            if not name:
                messagebox.showerror("Validation Error", "Patient name is required.")
                return
            if age and not age.isdigit():
                messagebox.showerror("Validation Error", "Age must be a number.")
                return
            if mobile and not validate_mobile_number(mobile):
                messagebox.showerror("Validation Error", "Mobile number must be exactly 10 digits or empty.")
                return

            # Collect medicine data
            meds_data = []
            for med in self.meds:
                try:
                    mname = med['name'].get().strip().title()
                    if not mname:
                        continue
                        
                    start = med['start'].get_date().strftime("%Y-%m-%d")
                    qty_text = med['qty'].get().strip()
                    freq = med['freq'].get().strip().upper()
                    end = med['end'].get_date().strftime("%Y-%m-%d")

                    if not qty_text.isdigit() or int(qty_text) <= 0:
                        messagebox.showerror("Validation Error", "Quantity must be a positive integer.")
                        return
                    if freq not in ["OD", "BD", "TDS", "QID"]:
                        messagebox.showerror("Validation Error", "Frequency must be one of OD, BD, TDS, QID.")
                        return

                    meds_data.append({
                        "MedicineName": mname,
                        "StartDate": start,
                        "Quantity": int(qty_text),
                        "Frequency": freq,
                        "EndDate": end
                    })
                except Exception as e:
                    messagebox.showerror("Medicine Error", f"Invalid medicine data:\n{str(e)}")
                    return

            if not meds_data:
                messagebox.showerror("Validation Error", "At least one medicine must be provided.")
                return

            # Save to database
            try:
                # Get the next available patient ID
                next_id = get_next_available_patient_id()
                if next_id is None:
                    raise Exception("Could not determine next patient ID")
                
                # Insert with specific ID to fill gaps
                cursor.execute("""
                    INSERT INTO Patients (PatientID, Name, Age, Gender, Address, MobileNumber) 
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (next_id, name, int(age) if age else None, gender, address, mobile if mobile else None))
                
                patient_id = next_id  # Use our assigned ID

                for med in meds_data:
                    cursor.execute("""
                        INSERT INTO Medicines (PatientID, MedicineName, StartDate, Quantity, Frequency, EndDate)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (patient_id, med["MedicineName"], med["StartDate"], med["Quantity"], med["Frequency"], med["EndDate"]))
                
                conn.commit()
                messagebox.showinfo("Success", "Patient and medicines saved.")
                self.clear_form()
                self.load()
                
            except sqlite3.Error as e:
                conn.rollback()
                messagebox.showerror("Database Error", f"Failed to save data:\n{str(e)}")
                traceback.print_exc()
                
        except Exception as e:
            messagebox.showerror("Save Error", f"An unexpected error occurred:\n{str(e)}")
            traceback.print_exc()

    def load(self):
        try:
            # Clear existing treeview data
            for row in self.tree.get_children():
                self.tree.delete(row)

            # Fetch data from database
            cursor.execute("""
                SELECT P.PatientID, P.Name, P.Age, P.Gender, P.Address, P.MobileNumber, 
                       M.MedicineName, M.StartDate, M.Quantity, M.Frequency, M.EndDate
                FROM Patients P
                LEFT JOIN Medicines M ON P.PatientID = M.PatientID
                ORDER BY P.PatientID
            """)
            rows = cursor.fetchall()
            self.populate_treeview(rows)
                    
        except sqlite3.Error as e:
            messagebox.showerror("Database Error", f"Failed to load data:\n{str(e)}")
            traceback.print_exc()
        except Exception as e:
            messagebox.showerror("Load Error", f"An unexpected error occurred:\n{str(e)}")
            traceback.print_exc()

    def select_record(self, event):
        try:
            selected = self.tree.focus()
            if not selected:
                return
                
            values = self.tree.item(selected, "values")
            if not values:
                return
                
            patient_id = values[0]

            # Fetch patient data
            cursor.execute("""
                SELECT Name, Age, Gender, Address, MobileNumber 
                FROM Patients 
                WHERE PatientID=?
            """, (patient_id,))
            p_data = cursor.fetchone()
            
            if not p_data:
                messagebox.showerror("Error", "Patient not found.")
                return

            # Populate patient fields
            self.name.delete(0, tk.END)
            self.name.insert(0, p_data[0])
            
            self.age.delete(0, tk.END)
            self.age.insert(0, p_data[1] if p_data[1] is not None else "")
            
            self.gender.set(p_data[2] or "")
            
            self.address.delete(0, tk.END)
            self.address.insert(0, p_data[3] or "")
            
            self.mobile.delete(0, tk.END)
            self.mobile.insert(0, p_data[4] or "")

            # Clear existing medicine rows
            for med in self.meds[:]:
                self.remove_medicine_row(med)

            # Fetch medicine data
            cursor.execute("""
                SELECT MedicineName, StartDate, Quantity, Frequency, EndDate 
                FROM Medicines 
                WHERE PatientID=?
            """, (patient_id,))
            meds = cursor.fetchall()
            
            # Add medicine rows and populate them
            for _ in meds:
                self.add_medicine_row()
                
            for i, med_data in enumerate(meds):
                try:
                    name, start, qty, freq, end = med_data
                    med = self.meds[i]
                    
                    med['name'].insert(0, name)
                    
                    if start:
                        med['start'].set_date(start)
                        
                    med['qty'].insert(0, str(qty))
                    med['freq'].set(freq)
                    
                    if end:
                        med['end'].config(state="normal")
                        med['end'].set_date(end)
                        med['end'].config(state="readonly")
                        
                except Exception as e:
                    messagebox.showerror("Medicine Load Error", f"Failed to load medicine data:\n{str(e)}")
                    continue

            self.editing_id = patient_id
            
        except Exception as e:
            messagebox.showerror("Selection Error", f"Failed to select record:\n{str(e)}")
            traceback.print_exc()

    def update(self):
        try:
            if not self.editing_id:
                messagebox.showerror("Error", "No patient selected for update.")
                return

            # Get and validate patient data
            name = self.name.get().strip().title()
            age = self.age.get().strip()
            gender = self.gender.get().strip()
            address = self.address.get().strip()
            mobile = self.mobile.get().strip()

            if not name:
                messagebox.showerror("Validation Error", "Patient name is required.")
                return
            if age and not age.isdigit():
                messagebox.showerror("Validation Error", "Age must be a number.")
                return
            if mobile and not validate_mobile_number(mobile):
                messagebox.showerror("Validation Error", "Mobile number must be exactly 10 digits or empty.")
                return

            # Collect medicine data
            meds_data = []
            for med in self.meds:
                try:
                    mname = med['name'].get().strip().title()
                    if not mname:
                        continue
                        
                    start = med['start'].get_date().strftime("%Y-%m-%d")
                    qty_text = med['qty'].get().strip()
                    freq = med['freq'].get().strip().upper()
                    end = med['end'].get_date().strftime("%Y-%m-%d")

                    if not qty_text.isdigit() or int(qty_text) <= 0:
                        messagebox.showerror("Validation Error", "Quantity must be a positive integer.")
                        return
                    if freq not in ["OD", "BD", "TDS", "QID"]:
                        messagebox.showerror("Validation Error", "Frequency must be one of OD, BD, TDS, QID.")
                        return

                    meds_data.append({
                        "MedicineName": mname,
                        "StartDate": start,
                        "Quantity": int(qty_text),
                        "Frequency": freq,
                        "EndDate": end
                    })
                except Exception as e:
                    messagebox.showerror("Medicine Error", f"Invalid medicine data:\n{str(e)}")
                    return

            if not meds_data:
                messagebox.showerror("Validation Error", "At least one medicine must be provided.")
                return

            # Update database
            try:
                cursor.execute("""
                    UPDATE Patients 
                    SET Name=?, Age=?, Gender=?, Address=?, MobileNumber=?
                    WHERE PatientID=?
                """, (name, int(age) if age else None, gender, address, mobile if mobile else None, self.editing_id))

                # Delete existing medicines and insert new ones
                cursor.execute("DELETE FROM Medicines WHERE PatientID=?", (self.editing_id,))
                
                for med in meds_data:
                    cursor.execute("""
                        INSERT INTO Medicines (PatientID, MedicineName, StartDate, Quantity, Frequency, EndDate)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (self.editing_id, med["MedicineName"], med["StartDate"], med["Quantity"], med["Frequency"], med["EndDate"]))
                
                conn.commit()
                messagebox.showinfo("Success", "Patient and medicines updated.")
                self.clear_form()
                self.load()
                
            except sqlite3.Error as e:
                conn.rollback()
                messagebox.showerror("Database Error", f"Failed to update data:\n{str(e)}")
                traceback.print_exc()
                
        except Exception as e:
            messagebox.showerror("Update Error", f"An unexpected error occurred:\n{str(e)}")
            traceback.print_exc()

    def delete(self):
        try:
            selected = self.tree.focus()
            if not selected:
                messagebox.showerror("Error", "No record selected to delete.")
                return
                
            values = self.tree.item(selected, "values")
            if not values:
                return
                
            patient_id = values[0]

            confirm = messagebox.askyesno(
                "Confirm Delete", 
                f"Are you sure you want to delete patient ID {patient_id} and all associated medicines?"
            )
            if not confirm:
                return

            try:
                cursor.execute("DELETE FROM Medicines WHERE PatientID=?", (patient_id,))
                cursor.execute("DELETE FROM Patients WHERE PatientID=?", (patient_id,))
                conn.commit()
                
                # Resequence to maintain sequential IDs
                resequence_patient_ids()
                self.load()
                messagebox.showinfo("Deleted", "Patient record deleted.")
                
            except sqlite3.Error as e:
                conn.rollback()
                messagebox.showerror("Database Error", f"Failed to delete record:\n{str(e)}")
                traceback.print_exc()
                
        except Exception as e:
            messagebox.showerror("Delete Error", f"An unexpected error occurred:\n{str(e)}")
            traceback.print_exc()

    def export_pdf(self):
        try:
            selected = self.tree.focus()
            if not selected:
                messagebox.showerror("Error", "No patient selected for PDF export.")
                return
                
            values = self.tree.item(selected, "values")
            if not values:
                return
                
            patient_id = values[0]

            # Fetch patient data
            cursor.execute("""
                SELECT Name, Age, Gender, Address, MobileNumber 
                FROM Patients 
                WHERE PatientID=?
            """, (patient_id,))
            p_data = cursor.fetchone()
            
            if not p_data:
                messagebox.showerror("Error", "Patient data not found.")
                return

            # Fetch medicine data
            cursor.execute("""
                SELECT MedicineName, StartDate, Quantity, Frequency, EndDate 
                FROM Medicines 
                WHERE PatientID=?
            """, (patient_id,))
            meds = cursor.fetchall()

            # Ask for save location
            file_path = filedialog.asksaveasfilename(
                defaultextension=".pdf",
                filetypes=[("PDF files", "*.pdf")],
                title="Save PDF as"
            )
            if not file_path:
                return

            # Generate PDF
            try:
                c = canvas.Canvas(file_path, pagesize=letter)
                width, height = letter
                
                # Patient header
                c.setFont("Helvetica-Bold", 16)
                c.drawString(50, height - 50, "Patient Details")
                
                # Patient info
                c.setFont("Helvetica", 12)
                y = height - 80
                
                info_lines = [
                    f"Patient ID: {patient_id}",
                    f"Name: {p_data[0]}",
                    f"Age: {p_data[1] if p_data[1] is not None else 'N/A'}",
                    f"Gender: {p_data[2] or 'N/A'}",
                    f"Address: {p_data[3] or 'N/A'}",
                    f"Mobile Number: {p_data[4] or 'N/A'}"
                ]
                
                for line in info_lines:
                    c.drawString(50, y, line)
                    y -= 20
                
                y -= 20  # Extra space before medicines
                
                # Medicine header
                c.setFont("Helvetica-Bold", 16)
                c.drawString(50, y, "Medicines")
                y -= 30
                
                if not meds:
                    c.setFont("Helvetica", 12)
                    c.drawString(50, y, "No medicines prescribed.")
                    y -= 20
                else:
                    c.setFont("Helvetica", 12)
                    for med in meds:
                        try:
                            medname, start, qty, freq, end = med
                            remaining = calculate_remaining_tablets(start, end, qty, freq)
                            
                            # Medicine name
                            c.setFont("Helvetica-Bold", 12)
                            c.drawString(50, y, medname)
                            y -= 20
                            
                            # Medicine details
                            c.setFont("Helvetica", 10)
                            details = [
                                f"Start Date: {start}",
                                f"Quantity: {qty} tablets",
                                f"Frequency: {freq}",
                                f"End Date: {end}",
                                f"Remaining Tablets: {remaining}",
                                "--------------------------------"
                            ]
                            
                            for detail in details:
                                c.drawString(70, y, detail)
                                y -= 15
                                
                            y -= 10  # Space between medicines
                            
                            # Page break if needed
                            if y < 100:
                                c.showPage()
                                y = height - 50
                                c.setFont("Helvetica", 12)
                                
                        except Exception as e:
                            messagebox.showerror("PDF Error", f"Failed to process medicine:\n{str(e)}")
                            continue
                
                c.save()
                messagebox.showinfo("Exported", f"Patient data exported to:\n{file_path}")
                
            except Exception as e:
                messagebox.showerror("PDF Error", f"Failed to generate PDF:\n{str(e)}")
                traceback.print_exc()
                
        except Exception as e:
            messagebox.showerror("Export Error", f"An unexpected error occurred:\n{str(e)}")
            traceback.print_exc()

if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = PatientCareApp(root)
        root.mainloop()
    except Exception as e:
        messagebox.showerror("Fatal Error", f"Application crashed:\n{str(e)}")
        traceback.print_exc()
    finally:
        try:
            conn.close()
        except:
            pass