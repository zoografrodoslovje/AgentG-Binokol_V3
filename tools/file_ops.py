"""
File operations tool for the Devin Agent system.
Provides file read, write, and list capabilities.
"""

import os
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime


class FileOps:
    """File operations toolkit."""
    
    def __init__(self, workspace_root: str = "."):
        """
        Initialize file operations.
        
        Args:
            workspace_root: Root directory for file operations
        """
        self.workspace_root = Path(workspace_root).resolve()
        self._ensure_workspace()
    
    def _ensure_workspace(self):
        """Ensure workspace directory exists."""
        self.workspace_root.mkdir(parents=True, exist_ok=True)
    
    def _resolve_path(self, path: str) -> Path:
        """Resolve a path relative to workspace root."""
        p = Path(path)
        if p.is_absolute():
            return p
        return self.workspace_root / p

    def _is_within_workspace(self, resolved: Path) -> bool:
        try:
            resolved.relative_to(self.workspace_root)
            return True
        except Exception:
            return False
    
    def write_file(self, path: str, content: str, 
                   create_dirs: bool = True) -> Dict[str, Any]:
        """
        Write content to a file.
        
        Args:
            path: File path (relative to workspace or absolute)
            content: Content to write
            create_dirs: Whether to create parent directories
            
        Returns:
            Dictionary with result info
        """
        try:
            file_path = self._resolve_path(path)
            
            if create_dirs:
                file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Handle different line endings based on file type
            # For Python files, use LF; for others, try to preserve existing
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            return {
                "success": True,
                "path": str(file_path),
                "bytes": file_path.stat().st_size,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "path": str(file_path) if 'file_path' in locals() else path
            }
    
    def read_file(self, path: str, limit: Optional[int] = None,
                  offset: int = 0) -> Dict[str, Any]:
        """
        Read contents of a file.
        
        Args:
            path: File path
            limit: Maximum lines to read (None for all)
            offset: Line number to start from (0-indexed)
            
        Returns:
            Dictionary with file contents
        """
        try:
            file_path = self._resolve_path(path)
            if not self._is_within_workspace(file_path.resolve()):
                return {"success": False, "error": "Path escapes workspace root", "path": str(file_path)}
            
            if not file_path.exists():
                return {
                    "success": False,
                    "error": "File not found",
                    "path": str(file_path)
                }
            
            raw = file_path.read_text(encoding="utf-8", errors="replace")
            lines = raw.splitlines()
            total_lines = len(lines)
            if limit is not None:
                content = "\n".join(lines[offset:offset + limit])
            else:
                content = raw
            
            return {
                "success": True,
                "path": str(file_path),
                "content": content,
                "total_lines": total_lines,
                "bytes": file_path.stat().st_size,
                "truncated": limit is not None and total_lines > limit
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "path": str(file_path) if 'file_path' in locals() else path
            }
    
    def list_files(self, path: str = ".", pattern: Optional[str] = None,
                   recursive: bool = False, include_dirs: bool = False) -> Dict[str, Any]:
        """
        List files in a directory.
        
        Args:
            path: Directory path
            pattern: Glob pattern to filter files
            recursive: Whether to recurse into subdirectories
            include_dirs: Whether to include directories in results
            
        Returns:
            Dictionary with file listing
        """
        try:
            dir_path = self._resolve_path(path)
            if not self._is_within_workspace(dir_path.resolve()):
                return {"success": False, "error": "Path escapes workspace root", "path": str(dir_path)}
            
            if not dir_path.exists():
                return {
                    "success": False,
                    "error": "Directory not found",
                    "path": str(dir_path)
                }
            
            files = []
            
            if recursive:
                for item in dir_path.rglob(pattern or "*"):
                    if include_dirs or item.is_file():
                        files.append({
                            "path": str(item),
                            "relative": str(item.relative_to(dir_path)),
                            "name": item.name,
                            "is_dir": item.is_dir(),
                            "size": item.stat().st_size if item.is_file() else 0,
                            "modified": datetime.fromtimestamp(
                                item.stat().st_mtime
                            ).isoformat() if item.exists() else None
                        })
            else:
                for item in dir_path.glob(pattern or "*"):
                    if include_dirs or item.is_file():
                        files.append({
                            "path": str(item),
                            "relative": item.name,
                            "name": item.name,
                            "is_dir": item.is_dir(),
                            "size": item.stat().st_size if item.is_file() else 0,
                            "modified": datetime.fromtimestamp(
                                item.stat().st_mtime
                            ).isoformat() if item.exists() else None
                        })
            
            # Sort: dirs first, then name
            files.sort(key=lambda x: (0 if x.get("is_dir") else 1, (x.get("relative") or "").lower()))
            
            return {
                "success": True,
                "path": str(dir_path),
                "files": files,
                "count": len(files)
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "path": str(dir_path) if 'dir_path' in locals() else path
            }
    
    def delete_file(self, path: str, permanent: bool = False) -> Dict[str, Any]:
        """
        Delete a file (or move to trash if not permanent).
        
        Args:
            path: File path
            permanent: If False, moves to .trash directory
            
        Returns:
            Dictionary with result info
        """
        try:
            file_path = self._resolve_path(path)
            
            if not file_path.exists():
                return {
                    "success": False,
                    "error": "File not found",
                    "path": str(file_path)
                }
            
            if permanent:
                file_path.unlink()
            else:
                trash_dir = self.workspace_root / ".trash"
                trash_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                trash_name = f"{timestamp}_{file_path.name}"
                shutil.move(str(file_path), str(trash_dir / trash_name))
            
            return {
                "success": True,
                "path": str(file_path),
                "action": "deleted" if permanent else "trashed"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "path": str(file_path) if 'file_path' in locals() else path
            }
    
    def copy_file(self, source: str, destination: str) -> Dict[str, Any]:
        """
        Copy a file.
        
        Args:
            source: Source file path
            destination: Destination file path
            
        Returns:
            Dictionary with result info
        """
        try:
            src_path = self._resolve_path(source)
            dst_path = self._resolve_path(destination)
            
            if not src_path.exists():
                return {
                    "success": False,
                    "error": "Source file not found",
                    "path": str(src_path)
                }
            
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src_path), str(dst_path))
            
            return {
                "success": True,
                "source": str(src_path),
                "destination": str(dst_path),
                "bytes": dst_path.stat().st_size
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "source": str(src_path) if 'src_path' in locals() else source
            }
    
    def create_directory(self, path: str) -> Dict[str, Any]:
        """
        Create a directory.
        
        Args:
            path: Directory path
            
        Returns:
            Dictionary with result info
        """
        try:
            dir_path = self._resolve_path(path)
            dir_path.mkdir(parents=True, exist_ok=True)
            
            return {
                "success": True,
                "path": str(dir_path)
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "path": path
            }
    
    def file_exists(self, path: str) -> bool:
        """Check if a file exists."""
        return self._resolve_path(path).exists()
    
    def get_file_info(self, path: str) -> Dict[str, Any]:
        """Get file information."""
        try:
            file_path = self._resolve_path(path)
            
            if not file_path.exists():
                return {
                    "success": False,
                    "error": "File not found"
                }
            
            stat = file_path.stat()
            
            return {
                "success": True,
                "path": str(file_path),
                "size": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "is_file": file_path.is_file(),
                "is_dir": file_path.is_dir()
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
