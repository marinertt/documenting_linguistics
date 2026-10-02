"""Native folder selection for the local macOS app server."""
import subprocess
import sys
import threading

_picker_lock = threading.Lock()


def choose_folder():
    if sys.platform != 'darwin':
        raise ValueError('The native folder picker requires macOS. Enter the folder path instead.')
    if not _picker_lock.acquire(blocking=False):
        raise ValueError('A folder picker is already open. Choose or cancel that folder first.')
    try:
        # Fixed script: no user-provided text is interpreted as AppleScript.
        script = '''
        try
            tell application "System Events"
                activate
                set selectedFolder to choose folder with prompt "Choose a folder for Fieldnotes"
            end tell
            return POSIX path of selectedFolder
        on error number -128
            return ""
        end try
        '''
        try:
            result = subprocess.run(['/usr/bin/osascript', '-e', script],
                                    capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            raise ValueError('Folder selection timed out. Try again or enter a path.') from None
        if result.returncode:
            raise ValueError('Could not open the folder picker. Check macOS Automation permissions for the app running Fieldnotes, or enter a path.')
        path = result.stdout.strip()
        return {'path': path or None, 'cancelled': not bool(path)}
    finally:
        _picker_lock.release()
