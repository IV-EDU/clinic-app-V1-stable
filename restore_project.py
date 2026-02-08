import shutil
import os
import sys

def restore_backup(backup_name):
    source_dir = os.path.dirname(os.path.abspath(__file__))
    backup_path = os.path.join(source_dir, ".backups", backup_name)
    
    if not os.path.exists(backup_path):
        print(f"Error: Backup '{backup_name}' not found in .backups folder.")
        print("Available backups:")
        backups_dir = os.path.join(source_dir, ".backups")
        if os.path.exists(backups_dir):
            for d in os.listdir(backups_dir):
                print(f" - {d}")
        return

    print(f"Restoring from: {backup_name}...")
    print("WARNING: This will overwrite files in the current directory.")
    confirm = input("Type 'yes' to confirm: ")
    if confirm.lower() != 'yes':
        print("Restore cancelled.")
        return

    # Exclude valuable untracked data we might want to keep? 
    # Usually restoring means reverting code. Database might be overwritten if included in backup.
    # Our backup script INCLUDES clinic.db.
    
    try:
        # Copy from backup to current
        for root, dirs, files in os.walk(backup_path):
            rel_path = os.path.relpath(root, backup_path)
            dest_root = os.path.join(source_dir, rel_path)
            
            if not os.path.exists(dest_root):
                os.makedirs(dest_root)
                
            for file in files:
                src_file = os.path.join(root, file)
                dst_file = os.path.join(dest_root, file)
                shutil.copy2(src_file, dst_file)
                
        print("Restore completed successfully.")
        
    except Exception as e:
        print(f"Restore failed: {str(e)}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python restore_project.py <backup_folder_name>")
        # List available
        print("\nAvailable backups:")
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".backups")
        if os.path.exists(base):
            for d in sorted(os.listdir(base)):
                print(f" - {d}")
    else:
        restore_backup(sys.argv[1])
