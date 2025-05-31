#!/usr/bin/env python3
"""
Dual Pane RClone File Manager v1.9 - Final Fixed Edition with Animations
İki panelli dosya yöneticisi + Klasör karşılaştırma - Tüm hatalar düzeltildi + Animasyonlar
"""

import os, sys, subprocess, threading, webbrowser, signal
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# ================================ CONSTANTS ================================

OPERATION_TIMEOUT = 300  # 5 dakika
COPY_TIMEOUT = 600      # 10 dakika

# ================================ MODELS ================================

@dataclass
class FileItem:
    name: str
    path: str
    is_dir: bool
    size: str = ""
    modified: str = ""
    remote: str = ""

@dataclass
class TransferResult:
    success_files: List[str] = field(default_factory=list)
    failed_files: List[str] = field(default_factory=list)
    error_details: Dict[str, List[str]] = field(default_factory=dict)

@dataclass
class ComparisonResult:
    left_only: List[FileItem] = field(default_factory=list)
    right_only: List[FileItem] = field(default_factory=list)
    different: List[tuple] = field(default_factory=list)
    same: List[tuple] = field(default_factory=list)

# ================================ ANIMATION CLASS ================================

class ProgressAnimation:
    """Çalışma durumunu gösteren animasyon sınıfı"""
    def __init__(self, status_label):
        self.status_label = status_label
        self.is_running = False
        self.animation_thread = None
        self.base_text = ""
        self.spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.dots_chars = [".", "..", "...", ""]
        self.current_frame = 0
        self.animation_type = "spinner"  # "spinner" veya "dots"
    
    def start(self, text, animation_type="spinner"):
        """Animasyonu başlat"""
        if self.is_running:
            self.stop()
        
        self.base_text = text
        self.animation_type = animation_type
        self.is_running = True
        self.current_frame = 0
        self.animation_thread = threading.Thread(target=self._animate, daemon=True)
        self.animation_thread.start()
    
    def stop(self):
        """Animasyonu durdur"""
        self.is_running = False
        if self.animation_thread:
            self.animation_thread.join(timeout=0.1)
        self.status_label.config(text="Hazır")
    
    def _animate(self):
        """Animasyon döngüsü"""
        while self.is_running:
            try:
                if self.animation_type == "spinner":
                    char = self.spinner_chars[self.current_frame % len(self.spinner_chars)]
                    display_text = f"{char} {self.base_text}"
                else:  # dots
                    dots = self.dots_chars[self.current_frame % len(self.dots_chars)]
                    display_text = f"{self.base_text}{dots}"
                
                # UI güncellemesi ana thread'de yapılmalı
                if hasattr(self.status_label, 'winfo_exists') and self.status_label.winfo_exists():
                    self.status_label.after_idle(lambda: self.status_label.config(text=display_text))
                else:
                    break
                
                self.current_frame += 1
                threading.Event().wait(0.1)  # 100ms bekle
                
            except Exception:
                break

# ================================ UTILITIES ================================

def normalize_path(path):
    """Path normalizasyon için ortak fonksiyon"""
    return str(Path(path)).replace('\\', '/')

def get_rclone_path():
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(sys.executable), 'rclone.exe')
    local_path = os.path.join(os.path.dirname(__file__), 'rclone', 'rclone.exe')
    return local_path if os.path.exists(local_path) else 'rclone'

def format_size(size_str: str) -> str:
    try:
        size = int(size_str)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024: return f"{size} {unit}"
            size //= 1024
        return f"{size} TB"
    except: return size_str

def show_info(title, msg): messagebox.showinfo(title, msg)
def show_warning(title, msg): messagebox.showwarning(title, msg)
def show_error(title, msg): messagebox.showerror(title, msg)
def ask_yes_no(title, msg): return messagebox.askyesno(title, msg)

# ================================ RCLONE SERVICE ================================

class RCloneService:
    def __init__(self, log_callback):
        self.rclone_path = get_rclone_path()
        self.log = log_callback
        self.active_processes = set()
        self.running = False
        self.current_process = None
    
    def check_rclone(self):
        try:
            result = subprocess.run([self.rclone_path, 'version'], capture_output=True, text=True, 
                                  timeout=10, encoding='utf-8', errors='ignore')
            if result.returncode == 0 and result.stdout:
                stdout = result.stdout.strip()
                if stdout:
                    version = stdout.split('\n')[0]
                    return True, f"{version} {'(Bundle)' if getattr(sys, 'frozen', False) else ''}"
            return False, "rclone bulunamadı"
        except Exception as e:
            return False, f"RClone bulunamadı: {self.rclone_path} - {e}"
    
    def load_remotes(self):
        try:
            result = subprocess.run([self.rclone_path, 'listremotes'], capture_output=True, text=True, 
                                  timeout=30, encoding='utf-8', errors='ignore')
            if result.returncode == 0 and result.stdout:
                stdout = result.stdout.strip()
                if stdout:
                    return [r.strip() for r in stdout.split('\n') if r.strip()]
            return []
        except Exception as e:
            self.log(f"❌ Remote yükleme hatası: {e}")
            return []
    
    def list_files(self, remote: str, path: str, recursive=False) -> List[FileItem]:
        files = []
        if path != "/" and not recursive:
            parent = normalize_path(str(Path(path).parent))
            files.append(FileItem("..", "/" if parent == "." else parent, True, "", "", remote))
        
        try:
            # Get directories
            cmd = [self.rclone_path, 'lsd', f"{remote}{path}"]
            if recursive: cmd.append('-R')
            else: cmd.extend(['--max-depth', '1'])
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=OPERATION_TIMEOUT, 
                                  encoding='utf-8', errors='ignore')
            if result.returncode == 0 and result.stdout:
                stdout = result.stdout.strip()
                if stdout:
                    for line in stdout.split('\n'):
                        line = line.strip()
                        if line:
                            parts = line.split()
                            if len(parts) >= 5:
                                name = ' '.join(parts[4:])
                                dir_path = name if recursive else normalize_path(str(Path(path) / name))
                                files.append(FileItem(name, dir_path, True, "", f"{parts[1]} {parts[2]}", remote))
            
            # Get files
            cmd = [self.rclone_path, 'lsl', f"{remote}{path}"]
            if recursive: cmd.append('-R')
            else: cmd.extend(['--max-depth', '1'])
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=OPERATION_TIMEOUT, 
                                  encoding='utf-8', errors='ignore')
            if result.returncode == 0 and result.stdout:
                stdout = result.stdout.strip()
                if stdout:
                    for line in stdout.split('\n'):
                        line = line.strip()
                        if line:
                            parts = line.split()
                            if len(parts) >= 5:
                                name = ' '.join(parts[4:])
                                file_path = name if recursive else normalize_path(str(Path(path) / name))
                                files.append(FileItem(name, file_path, False, parts[0], f"{parts[1]} {parts[2]}", remote))
        except subprocess.TimeoutExpired:
            raise Exception(f"Timeout ({OPERATION_TIMEOUT//60} dakika)")
        except Exception as e:
            raise Exception(f"Listeleme hatası: {e}")
        return files
    
    def _create_process(self, cmd_type, source, dest="", is_dir=False, is_test=False, ignore_existing=True, ignore_errors=True):
        cmd = [self.rclone_path]
        
        if cmd_type == "copy":
            cmd.extend(['copyfile' if not is_dir else 'copy', source, dest])
            if is_dir: cmd.append('--create-empty-src-dirs')
        elif cmd_type == "sync": cmd.extend(['sync', source, dest])
        elif cmd_type == "delete": cmd.extend(['purge' if is_dir else 'delete', source])
        
        cmd.extend(['--progress', '--verbose', '--transfers', '3'])
        if cmd_type in ["copy", "sync"]:
            if ignore_existing: cmd.append('--ignore-existing')
            if ignore_errors: cmd.append('--ignore-errors')
            if is_test: cmd.append('--dry-run')
        
        # Windows encoding fix
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                 text=True, bufsize=1, encoding='utf-8', errors='ignore')
        self.active_processes.add(process)
        return process
    
    def copy_files(self, files: List[FileItem], source_remote: str, dest_remote: str, dest_path: str, 
                   is_test: bool, ignore_existing: bool, ignore_errors: bool, completion_callback=None):
        if self.running: return False
        self.running = True
        threading.Thread(target=self._copy_worker, args=(files, source_remote, dest_remote, dest_path, 
                        is_test, ignore_existing, ignore_errors, completion_callback), daemon=True).start()
        return True
    
    def _copy_worker(self, files, source_remote, dest_remote, dest_path, is_test, ignore_existing, ignore_errors, callback):
        try:
            result = TransferResult()
            op = "TEST" if is_test else "KOPYALAMA"
            self.log(f"🚀 {op} başladı - {len(files)} öğe")
            
            for i, file_item in enumerate(files, 1):
                if not self.running: break
                self.log(f"📋 [{i}/{len(files)}] {file_item.name}")
                
                try:
                    source_path = f"{source_remote}{file_item.path}"
                    dest_full = f"{dest_remote}{normalize_path(str(Path(dest_path) / file_item.name))}"
                    
                    self.current_process = self._create_process("copy", source_path, dest_full, 
                                         file_item.is_dir, is_test, ignore_existing, ignore_errors)
                    
                    stdout, stderr = self.current_process.communicate(timeout=COPY_TIMEOUT)
                    return_code = self.current_process.returncode
                    self.active_processes.discard(self.current_process)
                    
                    if return_code == 0:
                        result.success_files.append(file_item.name)
                        self.log(f"✅ {file_item.name}")
                    else:
                        result.failed_files.append(file_item.name)
                        error_msg = stderr[:200] if stderr else stdout[:200] if stdout else "Bilinmeyen hata"
                        result.error_details[file_item.name] = [error_msg]
                        self.log(f"❌ {file_item.name}")
                        
                except subprocess.TimeoutExpired:
                    result.failed_files.append(file_item.name)
                    result.error_details[file_item.name] = [f"Timeout ({COPY_TIMEOUT//60} dakika)"]
                    self.log(f"⏰ {file_item.name} - Timeout")
                except Exception as e:
                    result.failed_files.append(file_item.name)
                    result.error_details[file_item.name] = [str(e)]
                    self.log(f"💥 {file_item.name} - {e}")
            
            self.log(f"🏁 {op} tamamlandı - ✅{len(result.success_files)} ❌{len(result.failed_files)}")
            if callback: callback(result, is_test)
        except Exception as e: 
            self.log(f"💥 {op} hatası: {e}")
        finally: 
            self.running = False
            self.current_process = None
    
    def compare_directories(self, left_remote: str, left_path: str, right_remote: str, right_path: str, 
                           criteria: List[str], completion_callback=None):
        if self.running: return False
        self.running = True
        threading.Thread(target=self._compare_worker, args=(left_remote, left_path, right_remote, right_path, 
                        criteria, completion_callback), daemon=True).start()
        return True
    
    def _compare_worker(self, left_remote, left_path, right_remote, right_path, criteria, callback):
        try:
            self.log("🔍 KLASÖR KARŞILAŞTIRMA BAŞLADI")
            self.log(f"📤 Sol: {left_remote}{left_path}")
            self.log(f"📥 Sağ: {right_remote}{right_path}")
            
            left_files = [f for f in self.list_files(left_remote, left_path, recursive=True) if f.name != ".."]
            right_files = [f for f in self.list_files(right_remote, right_path, recursive=True) if f.name != ".."]
            
            self.log(f"📊 Sol: {len(left_files)} öğe, Sağ: {len(right_files)} öğe")
            
            result = ComparisonResult()
            right_dict = {normalize_path(rf.path if rf.path.startswith('/') else '/' + rf.path): rf for rf in right_files}
            
            for lf in left_files:
                left_key = normalize_path(lf.path if lf.path.startswith('/') else '/' + lf.path)
                
                if left_key in right_dict:
                    rf = right_dict[left_key]
                    is_different = False
                    
                    if "isim" in criteria and lf.name != rf.name: is_different = True
                    if "boyut" in criteria and not lf.is_dir and not rf.is_dir and lf.size != rf.size: is_different = True
                    if "tarih" in criteria and lf.modified != rf.modified: is_different = True
                    
                    if is_different: result.different.append((lf, rf))
                    else: result.same.append((lf, rf))
                    
                    del right_dict[left_key]
                else: 
                    result.left_only.append(lf)
            
            for rf in right_dict.values(): 
                result.right_only.append(rf)
            
            self.log(f"📊 SONUÇ: Sadece solda:{len(result.left_only)}, Sadece sağda:{len(result.right_only)}, Farklı:{len(result.different)}, Aynı:{len(result.same)}")
            
            if callback: callback(result)
        except Exception as e: 
            self.log(f"💥 Karşılaştırma hatası: {e}")
        finally: 
            self.running = False
    
    def stop_operation(self):
        self.running = False
        if self.current_process:
            try: 
                self.current_process.terminate()
                self.log("🛑 İşlem durduruldu")
            except: pass
    
    def cleanup(self):
        self.stop_operation()
        for process in list(self.active_processes):
            try:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=2)
            except: pass
        self.active_processes.clear()

# ================================ UI DIALOGS ================================

class DialogManager:
    @staticmethod
    def show_rclone_install():
        show_error("RClone Gerekli", "RClone kurulu değil!\n\nKurulum:\nWindows: winget install Rclone.Rclone\nmacOS: brew install rclone\nLinux: sudo apt install rclone")
    
    @staticmethod
    def show_copy_confirmation(file_count, op_type, source, dest, test_mode):
        msg = f"{op_type} işlemi:\n\n📋 {file_count} öğe\n📤 {source} → 📥 {dest}"
        if test_mode: msg += "\n\n🧪 Test Modu"
        return ask_yes_no(f"{op_type} Onayı", msg)
    
    @staticmethod
    def show_comparison_dialog(parent, start_callback):
        dialog = tk.Toplevel(parent)
        dialog.title("Klasör Karşılaştırma")
        dialog.geometry("500x400")
        dialog.transient(parent)
        dialog.grab_set()
        dialog.resizable(False, False)
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (500 // 2)
        y = (dialog.winfo_screenheight() // 2) - (400 // 2)
        dialog.geometry(f"500x400+{x}+{y}")
        
        # Main container
        main_frame = ttk.Frame(dialog)
        main_frame.pack(fill='both', expand=True, padx=20, pady=20)
        
        # Title
        title_label = ttk.Label(main_frame, text="🔍 Klasör Karşılaştırma", 
                               font=('Arial', 16, 'bold'))
        title_label.pack(pady=(0, 20))
        
        # Criteria frame
        criteria_frame = ttk.LabelFrame(main_frame, text="Karşılaştırma Kriterleri")
        criteria_frame.pack(fill='x', pady=(0, 20))
        
        # Add padding inside criteria frame
        criteria_inner = ttk.Frame(criteria_frame)
        criteria_inner.pack(fill='x', padx=15, pady=15)
        
        name_var = tk.BooleanVar(value=True)
        size_var = tk.BooleanVar(value=True)
        date_var = tk.BooleanVar(value=False)
        
        ttk.Checkbutton(criteria_inner, text="📝 İsim", variable=name_var).pack(anchor='w', pady=3)
        ttk.Checkbutton(criteria_inner, text="📏 Boyut", variable=size_var).pack(anchor='w', pady=3)
        ttk.Checkbutton(criteria_inner, text="📅 Tarih", variable=date_var).pack(anchor='w', pady=3)
        
        # Info label
        info_label = ttk.Label(main_frame, text="ℹ️ Karşılaştırma işlemi zaman alabilir", 
                              font=('Arial', 9))
        info_label.pack(pady=(0, 30))
        
        def start_comparison():
            criteria = []
            if name_var.get(): criteria.append("isim")
            if size_var.get(): criteria.append("boyut")
            if date_var.get(): criteria.append("tarih")
            
            if not criteria:
                show_warning("Uyarı", "En az bir kriter seçmelisiniz!")
                return
            
            dialog.destroy()
            start_callback(criteria)
        
        def close_dialog():
            dialog.destroy()
        
        # Buttons frame with explicit packing
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill='x', side='bottom')
        
        # Create buttons with explicit sizing
        compare_btn = ttk.Button(btn_frame, text="🔍 Karşılaştır", command=start_comparison)
        compare_btn.pack(side='left', padx=(0, 10), ipadx=10, ipady=5)
        
        cancel_btn = ttk.Button(btn_frame, text="❌ İptal", command=close_dialog)
        cancel_btn.pack(side='left', ipadx=10, ipady=5)
        
        # Bind keys
        dialog.bind('<Return>', lambda e: start_comparison())
        dialog.bind('<Escape>', lambda e: close_dialog())
        
        # Force update and focus
        dialog.update()
        dialog.focus_force()
        compare_btn.focus_set()
    
    @staticmethod
    def show_result_report(parent, result, title):
        window = tk.Toplevel(parent)
        window.title(title)
        window.geometry("700x500")
        window.transient(parent)
        
        # Center the window
        window.update_idletasks()
        x = (window.winfo_screenwidth() // 2) - (700 // 2)
        y = (window.winfo_screenheight() // 2) - (500 // 2)
        window.geometry(f"700x500+{x}+{y}")
        
        # Header
        header_frame = ttk.Frame(window)
        header_frame.pack(fill='x', padx=10, pady=10)
        ttk.Label(header_frame, text=title, font=('Arial', 14, 'bold')).pack()
        
        # Text widget with scrollbar
        text_frame = ttk.Frame(window)
        text_frame.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        
        text_widget = scrolledtext.ScrolledText(text_frame, wrap=tk.WORD, font=('Consolas', 10))
        text_widget.pack(fill='both', expand=True)
        
        if isinstance(result, TransferResult):
            content = f"İŞLEM RAPORU\n{'='*50}\n\n"
            content += f"✅ Başarılı: {len(result.success_files)}\n"
            content += f"❌ Hatalı: {len(result.failed_files)}\n\n"
            
            if result.success_files:
                content += "BAŞARILI DOSYALAR:\n" + "-"*30 + "\n"
                for f in result.success_files: 
                    content += f"  ✅ {f}\n"
                content += "\n"
            
            if result.failed_files:
                content += "HATALI DOSYALAR:\n" + "-"*30 + "\n"
                for f in result.failed_files: 
                    content += f"  ❌ {f}\n"
                    if f in result.error_details:
                        for error in result.error_details[f]:
                            content += f"     💬 {error}\n"
                content += "\n"
        
        elif isinstance(result, ComparisonResult):
            content = f"KARŞILAŞTIRMA RAPORU\n{'='*50}\n\n"
            content += f"📤 Sadece solda: {len(result.left_only)}\n"
            content += f"📥 Sadece sağda: {len(result.right_only)}\n"
            content += f"🔄 Farklı: {len(result.different)}\n"
            content += f"✅ Aynı: {len(result.same)}\n\n"
            
            if result.left_only:
                content += "SADECE SOLDA:\n" + "-"*30 + "\n"
                for item in result.left_only:
                    icon = "📁" if item.is_dir else "📄"
                    content += f"  {icon} {item.path}\n"
                content += "\n"
            
            if result.right_only:
                content += "SADECE SAĞDA:\n" + "-"*30 + "\n"
                for item in result.right_only:
                    icon = "📁" if item.is_dir else "📄"
                    content += f"  {icon} {item.path}\n"
                content += "\n"
            
            if result.different:
                content += "FARKLI DOSYALAR:\n" + "-"*30 + "\n"
                for left_item, right_item in result.different:
                    content += f"  🔄 {left_item.path}\n"
                content += "\n"
        else:
            content = "Rapor bulunamadı."
        
        text_widget.insert(tk.END, content)
        text_widget.config(state='disabled')
        
        # Close button
        btn_frame = ttk.Frame(window)
        btn_frame.pack(fill='x', padx=10, pady=10)
        ttk.Button(btn_frame, text="❌ Kapat", command=window.destroy).pack()
        
        # Bind Escape key
        window.bind('<Escape>', lambda e: window.destroy())

# ================================ MAIN APPLICATION ================================

class DualPaneRCloneManager:
    def __init__(self):
        self.window = tk.Tk()
        self.window.title("Dual Pane RClone File Manager v1.9 - Final Fixed")
        self.window.geometry("1400x900")
        
        # Services
        self.rclone = RCloneService(self.log)
        
        # State
        self.left_remote = self.right_remote = None
        self.left_path = self.right_path = "/"
        self.left_files = self.right_files = []
        self.test_mode = tk.BooleanVar(value=False)
        self.last_result = None
        
        # UI Variables
        self.left_remote_var = tk.StringVar()
        self.right_remote_var = tk.StringVar()
        self.left_path_var = tk.StringVar(value="/")
        self.right_path_var = tk.StringVar(value="/")
        
        # Animation
        self.animation = None
        
        self.setup_ui()
        self.check_rclone()
        self.window.protocol("WM_DELETE_WINDOW", self.quit_app)
    
    def setup_ui(self):
        # Configure styles
        style = ttk.Style()
        style.configure("Title.TLabel", font=('Arial', 11, 'bold'))
        style.configure("Large.TCheckbutton", font=('Arial', 10))
        
        # Toolbar
        toolbar = ttk.Frame(self.window)
        toolbar.pack(fill='x', padx=5, pady=5)
        
        ttk.Button(toolbar, text="➡️ Sol → Sağ", command=self.copy_left_to_right).pack(side='left', padx=2)
        ttk.Button(toolbar, text="⬅️ Sağ → Sol", command=self.copy_right_to_left).pack(side='left', padx=2)
        ttk.Button(toolbar, text="🔍 Karşılaştır", command=self.compare_directories).pack(side='left', padx=2)
        ttk.Button(toolbar, text="📊 Rapor", command=self.show_report).pack(side='left', padx=2)
        ttk.Button(toolbar, text="⏹️ Durdur", command=self.stop_operation).pack(side='left', padx=2)
        
        ttk.Checkbutton(toolbar, text="🧪 Test Modu", variable=self.test_mode).pack(side='right', padx=5)
        
        # Main panels
        panels_frame = ttk.Frame(self.window)
        panels_frame.pack(fill='both', expand=True, padx=5)
        
        # Left panel
        left_frame = ttk.LabelFrame(panels_frame, text="📤 Sol Panel")
        left_frame.pack(side='left', fill='both', expand=True, padx=(0, 2))
        
        left_header = ttk.Frame(left_frame)
        left_header.pack(fill='x', padx=5, pady=5)
        
        self.left_remote_combo = ttk.Combobox(left_header, textvariable=self.left_remote_var, state="readonly")
        self.left_remote_combo.pack(side='left', fill='x', expand=True)
        self.left_remote_combo.bind('<<ComboboxSelected>>', self.on_left_remote_change)
        
        ttk.Button(left_header, text="🔄", command=self.refresh_left, width=3).pack(side='right', padx=(5, 0))
        
        left_path_frame = ttk.Frame(left_frame)
        left_path_frame.pack(fill='x', padx=5, pady=(0, 5))
        ttk.Label(left_path_frame, text="📁").pack(side='left')
        
        self.left_path_entry = ttk.Entry(left_path_frame, textvariable=self.left_path_var)
        self.left_path_entry.pack(side='left', fill='x', expand=True, padx=5)
        self.left_path_entry.bind('<Return>', self.on_left_path_change)
        
        self.left_tree = ttk.Treeview(left_frame, columns=('size', 'modified'), height=15)
        self.left_tree.heading('#0', text='İsim')
        self.left_tree.heading('size', text='Boyut')
        self.left_tree.heading('modified', text='Tarih')
        self.left_tree.column('#0', width=300)
        self.left_tree.column('size', width=100)
        self.left_tree.column('modified', width=150)
        self.left_tree.pack(fill='both', expand=True, padx=5, pady=(0, 5))
        self.left_tree.bind('<Double-1>', self.on_left_double_click)
        
        # Right panel
        right_frame = ttk.LabelFrame(panels_frame, text="📥 Sağ Panel")
        right_frame.pack(side='right', fill='both', expand=True, padx=(2, 0))
        
        right_header = ttk.Frame(right_frame)
        right_header.pack(fill='x', padx=5, pady=5)
        
        self.right_remote_combo = ttk.Combobox(right_header, textvariable=self.right_remote_var, state="readonly")
        self.right_remote_combo.pack(side='left', fill='x', expand=True)
        self.right_remote_combo.bind('<<ComboboxSelected>>', self.on_right_remote_change)
        
        ttk.Button(right_header, text="🔄", command=self.refresh_right, width=3).pack(side='right', padx=(5, 0))
        
        right_path_frame = ttk.Frame(right_frame)
        right_path_frame.pack(fill='x', padx=5, pady=(0, 5))
        ttk.Label(right_path_frame, text="📁").pack(side='left')
        
        self.right_path_entry = ttk.Entry(right_path_frame, textvariable=self.right_path_var)
        self.right_path_entry.pack(side='left', fill='x', expand=True, padx=5)
        self.right_path_entry.bind('<Return>', self.on_right_path_change)
        
        self.right_tree = ttk.Treeview(right_frame, columns=('size', 'modified'), height=15)
        self.right_tree.heading('#0', text='İsim')
        self.right_tree.heading('size', text='Boyut')
        self.right_tree.heading('modified', text='Tarih')
        self.right_tree.column('#0', width=300)
        self.right_tree.column('size', width=100)
        self.right_tree.column('modified', width=150)
        self.right_tree.pack(fill='both', expand=True, padx=5, pady=(0, 5))
        self.right_tree.bind('<Double-1>', self.on_right_double_click)
        
        # Log panel
        log_frame = ttk.LabelFrame(self.window, text="📝 İşlem Günlüğü")
        log_frame.pack(fill='x', padx=5, pady=5)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=6, font=('Consolas', 9))
        self.log_text.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Status bar
        status_frame = ttk.Frame(self.window)
        status_frame.pack(fill='x', padx=5, pady=2)
        self.status_label = ttk.Label(status_frame, text="Hazır", style="Title.TLabel")
        self.status_label.pack(side='left')
        
        # Animasyon nesnesi oluştur
        self.animation = ProgressAnimation(self.status_label)
    
    def log(self, message: str):
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
            self.log_text.see(tk.END)
            self.window.update_idletasks()
        except: 
            print(f"[LOG] {message}")
    
    def check_rclone(self):
        success, message = self.rclone.check_rclone()
        if success:
            self.log(f"✅ {message}")
            self.load_remotes()
        else:
            DialogManager.show_rclone_install()
            sys.exit(1)
    
    def load_remotes(self):
        remotes = self.rclone.load_remotes()
        if remotes:
            self.left_remote_combo['values'] = self.right_remote_combo['values'] = remotes
            self.log(f"📋 {len(remotes)} bağlantı yüklendi")
        else:
            self.log("⚠️ Henüz bağlantı yok - rclone config ile ekleyebilirsiniz")
    
    # Event handlers
    def on_left_remote_change(self, event=None):
        self.left_remote = self.left_remote_var.get()
        self.left_path = "/"
        self.left_path_var.set("/")
        self.refresh_left()
    
    def on_right_remote_change(self, event=None):
        self.right_remote = self.right_remote_var.get()
        self.right_path = "/"
        self.right_path_var.set("/")
        self.refresh_right()
    
    def on_left_path_change(self, event=None):
        self.left_path = self.left_path_var.get()
        self.refresh_left()
    
    def on_right_path_change(self, event=None):
        self.right_path = self.right_path_var.get()
        self.refresh_right()
    
    def on_left_double_click(self, event):
        selection = self.left_tree.selection()
        if selection:
            index = self.left_tree.index(selection[0])
            if index < len(self.left_files):
                file_item = self.left_files[index]
                if file_item.is_dir:
                    self.left_path = file_item.path
                    self.left_path_var.set(file_item.path)
                    self.refresh_left()
    
    def on_right_double_click(self, event):
        selection = self.right_tree.selection()
        if selection:
            index = self.right_tree.index(selection[0])
            if index < len(self.right_files):
                file_item = self.right_files[index]
                if file_item.is_dir:
                    self.right_path = file_item.path
                    self.right_path_var.set(file_item.path)
                    self.refresh_right()
    
    # Panel refresh
    def refresh_left(self):
        if not self.left_remote: return
        self.animation.start("Sol panel yenileniyor", "dots")
        threading.Thread(target=self._refresh_left_worker, daemon=True).start()
    
    def _refresh_left_worker(self):
        try:
            files = self.rclone.list_files(self.left_remote, self.left_path)
            self.window.after(0, self._update_left_tree, files)
        except Exception as e:
            self.window.after(0, self.log, f"❌ Sol panel hatası: {e}")
        finally:
            self.window.after(0, self.animation.stop)
    
    def refresh_right(self):
        if not self.right_remote: return
        self.animation.start("Sağ panel yenileniyor", "dots")
        threading.Thread(target=self._refresh_right_worker, daemon=True).start()
    
    def _refresh_right_worker(self):
        try:
            files = self.rclone.list_files(self.right_remote, self.right_path)
            self.window.after(0, self._update_right_tree, files)
        except Exception as e:
            self.window.after(0, self.log, f"❌ Sağ panel hatası: {e}")
        finally:
            self.window.after(0, self.animation.stop)
    
    def _update_left_tree(self, files: List[FileItem]):
        self.left_files = files
        for item in self.left_tree.get_children():
            self.left_tree.delete(item)
        
        for file_item in files:
            icon = "📁" if file_item.is_dir else "📄"
            name = f"{icon} {file_item.name}"
            size_str = "" if file_item.is_dir else format_size(file_item.size)
            self.left_tree.insert('', 'end', text=name, values=(size_str, file_item.modified))
    
    def _update_right_tree(self, files: List[FileItem]):
        self.right_files = files
        for item in self.right_tree.get_children():
            self.right_tree.delete(item)
        
        for file_item in files:
            icon = "📁" if file_item.is_dir else "📄"
            name = f"{icon} {file_item.name}"
            size_str = "" if file_item.is_dir else format_size(file_item.size)
            self.right_tree.insert('', 'end', text=name, values=(size_str, file_item.modified))
    
    # File selection helpers
    def get_selected_left_files(self) -> List[FileItem]:
        selected = []
        for item_id in self.left_tree.selection():
            index = self.left_tree.index(item_id)
            if index < len(self.left_files):
                file_item = self.left_files[index]
                if file_item.name != "..":
                    selected.append(file_item)
        return selected
    
    def get_selected_right_files(self) -> List[FileItem]:
        selected = []
        for item_id in self.right_tree.selection():
            index = self.right_tree.index(item_id)
            if index < len(self.right_files):
                file_item = self.right_files[index]
                if file_item.name != "..":
                    selected.append(file_item)
        return selected
    
    # Operations
    def copy_left_to_right(self):
        if not self.left_remote or not self.right_remote:
            show_error("Hata", "Her iki panel de bağlı olmalı!")
            return
        
        selected = self.get_selected_left_files()
        if not selected:
            show_warning("Uyarı", "Dosya/klasör seçin!")
            return
        
        op_type = "TEST" if self.test_mode.get() else "KOPYALAMA"
        if not DialogManager.show_copy_confirmation(len(selected), op_type, 
                                                   self.left_remote, f"{self.right_remote}{self.right_path}", 
                                                   self.test_mode.get()):
            return
        
        if self.rclone.running:
            show_warning("Uyarı", "Başka bir işlem devam ediyor!")
            return
        
        # Animasyonu başlat
        self.animation.start(f"{op_type} devam ediyor", "spinner")
        success = self.rclone.copy_files(selected, self.left_remote, self.right_remote, self.right_path,
                                        self.test_mode.get(), True, True, self._copy_completed)
        
        if not success:
            self.animation.stop()
    
    def copy_right_to_left(self):
        if not self.left_remote or not self.right_remote:
            show_error("Hata", "Her iki panel de bağlı olmalı!")
            return
        
        selected = self.get_selected_right_files()
        if not selected:
            show_warning("Uyarı", "Dosya/klasör seçin!")
            return
        
        op_type = "TEST" if self.test_mode.get() else "KOPYALAMA"
        if not DialogManager.show_copy_confirmation(len(selected), op_type, 
                                                   self.right_remote, f"{self.left_remote}{self.left_path}", 
                                                   self.test_mode.get()):
            return
        
        if self.rclone.running:
            show_warning("Uyarı", "Başka bir işlem devam ediyor!")
            return
        
        # Animasyonu başlat
        self.animation.start(f"{op_type} devam ediyor", "spinner")
        success = self.rclone.copy_files(selected, self.right_remote, self.left_remote, self.left_path,
                                        self.test_mode.get(), True, True, self._copy_completed)
        
        if not success:
            self.animation.stop()
    
    def _copy_completed(self, result: TransferResult, is_test: bool):
        self.last_result = result
        success_count = len(result.success_files)
        failed_count = len(result.failed_files)
        
        # Animasyonu durdur
        self.window.after(0, self.animation.stop)
        
        if failed_count == 0:
            op = "Test" if is_test else "Kopyalama"
            self.window.after(0, lambda: show_info("Başarılı", f"{op} tamamlandı!\n✅ {success_count} öğe"))
        else:
            self.window.after(0, lambda: show_warning("Kısmen Başarılı", f"✅ {success_count} ❌ {failed_count}"))
        
        if not is_test:
            self.window.after(0, self.refresh_left)
            self.window.after(0, self.refresh_right)
    
    def compare_directories(self):
        if not self.left_remote or not self.right_remote:
            show_error("Hata", "Her iki panel de bağlı olmalı!")
            return
        
        if self.rclone.running:
            show_warning("Uyarı", "Başka bir işlem devam ediyor!")
            return
        
        DialogManager.show_comparison_dialog(self.window, self._start_comparison)
    
    def _start_comparison(self, criteria: List[str]):
        # Animasyonu başlat
        self.animation.start("Klasörler karşılaştırılıyor", "spinner")
        success = self.rclone.compare_directories(self.left_remote, self.left_path, 
                                                 self.right_remote, self.right_path, 
                                                 criteria, self._comparison_completed)
        if not success:
            self.animation.stop()
    
    def _comparison_completed(self, result: ComparisonResult):
        self.last_result = result
        
        # Animasyonu durdur
        self.window.after(0, self.animation.stop)
        
        left_only = len(result.left_only)
        right_only = len(result.right_only)
        different = len(result.different)
        same = len(result.same)
        
        message = f"Karşılaştırma tamamlandı!\n\n📤 Sadece solda: {left_only}\n📥 Sadece sağda: {right_only}\n🔄 Farklı: {different}\n✅ Aynı: {same}\n\nDetaylı rapor için 'Rapor' butonuna tıklayın."
        self.window.after(0, lambda: show_info("Karşılaştırma Tamamlandı", message))
    
    def show_report(self):
        if self.last_result:
            title = "Transfer Raporu" if isinstance(self.last_result, TransferResult) else "Karşılaştırma Raporu"
            DialogManager.show_result_report(self.window, self.last_result, title)
        else:
            show_info("Rapor", "Henüz rapor yok.")
    
    def stop_operation(self):
        self.rclone.stop_operation()
        # Animasyonu durdur
        if self.animation:
            self.animation.stop()
    
    def quit_app(self):
        if self.rclone.running:
            if ask_yes_no("Çıkış", "İşlem devam ediyor. Çıkmak istediğinizden emin misiniz?"):
                self.rclone.cleanup()
                if self.animation:
                    self.animation.stop()
                self.window.destroy()
        else:
            self.rclone.cleanup()
            if self.animation:
                self.animation.stop()
            self.window.destroy()
    
    def run(self):
        try:
            self.window.mainloop()
        except KeyboardInterrupt:
            self.log("👋 Program kapatılıyor...")
            self.rclone.cleanup()
            if self.animation:
                self.animation.stop()
            sys.exit(0)

# ================================ MAIN ================================

def signal_handler(signum, frame):
    print("\n👋 Program kapatılıyor...")
    sys.exit(0)

def main():
    print("🚀 Dual Pane RClone File Manager v1.9 - Final Fixed başlatılıyor...")
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    if sys.version_info < (3, 8):
        print("❌ Bu program Python 3.8+ gerektirir!")
        sys.exit(1)
    
    try:
        app = DualPaneRCloneManager()
        app.run()
    except KeyboardInterrupt:
        print("\n👋 Program kapatılıyor...")
        sys.exit(0)
    except Exception as e:
        print(f"💥 Program hatası: {e}")
        input("Çıkmak için Enter'a basın...")
        sys.exit(1)

if __name__ == "__main__":
    main()