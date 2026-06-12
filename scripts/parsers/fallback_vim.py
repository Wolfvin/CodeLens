"""
Fallback VimScript Parser for CodeLens — regex-based extraction.
Extracts functions, commands, autocommands, variable declarations,
and keymap definitions from .vim files.
v1: Proper edge format for edge_resolver, function-level call edges,
    script-local and autoload function support, scoped variable tracking,
    and keymap pattern extraction.
"""

import re
from typing import Dict, List, Any, Optional


# Common VimScript keywords to skip when extracting identifiers
_VIM_KEYWORDS = frozenset({
    'if', 'else', 'elseif', 'endif', 'while', 'endwhile', 'for',
    'endfor', 'try', 'catch', 'finally', 'endtry', 'return', 'let',
    'call', 'function', 'endfunction', 'augroup', 'autocmd', 'command',
    'execute', 'echo', 'echom', 'normal', 'range',
    # Additional builtins that aren't real definitions
    'endif', 'endwhile', 'endfor', 'endtry', 'endfunction',
    'else', 'elseif', 'continue', 'break', 'throw',
    'echohl', 'echon', 'echomsg', 'echoerr', 'execute',
    'source', 'runtime', 'finish', 'sandbox',
    'fun', 'endfun',  # shorthand forms
})


def parse_vim_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse VimScript source using regex — extracts functions, commands,
    autocommands, variables, and keymaps.

    Returns dict with 'nodes' and 'edges' in the format expected by
    the backend registry and edge_resolver:
    - nodes: [{id, name, fn, type, file, line, domain, ref_count, status}, ...]
    - edges: [{from: node_id, to_fn: name}, ...] for function calls
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # Track defined function names for this file (short_name → node_id)
    defined_fns: Dict[str, str] = {}

    # Track current function scope for call-edge attribution
    # We build a list of (node_id, start_line, end_line) after pass 1
    fn_ranges: List[tuple] = []

    # ─── Pass 1: Extract declarations ──────────────────────────────

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Skip comment lines
        if stripped.startswith('"'):
            continue

        # --- Functions: function! Name(args), function Name(args) ---
        # Handles: function! MyFunc(), function! s:MyFunc(),
        #          function! myplugin#MyFunc(), function MyFunc()
        m = re.match(
            r'\s*function!?\s+((?:[sSgGbBwWtT]:)?(?:\w+#)*\w+)\s*\(([^)]*)\)',
            line,
        )
        if m:
            full_name = m.group(1)
            args = m.group(2).strip()
            # Derive short name: strip scope prefix and autoload path
            short_name = full_name
            if ':' in short_name:
                short_name = short_name.split(':', 1)[1]
            if '#' in short_name:
                short_name = short_name.split('#')[-1]

            node_id = f"{rel_path}:{i}"
            nodes.append({
                "id": node_id,
                "type": "function",
                "name": full_name,
                "fn": short_name,
                "file": rel_path,
                "line": i,
                "domain": "backend",
                "ref_count": 0,
                "status": "active",
                "args": args,
            })
            defined_fns[short_name] = node_id
            defined_fns[full_name] = node_id
            continue

        # --- Commands: command! Name ..., command -nargs=1 Name ... ---
        m = re.match(
            r'\s*command!?\s+(?:-\S+\s+)*(\w+)',
            line,
        )
        if m:
            cmd_name = m.group(1)
            if cmd_name not in _VIM_KEYWORDS:
                node_id = f"{rel_path}:{i}"
                nodes.append({
                    "id": node_id,
                    "type": "command",
                    "name": cmd_name,
                    "fn": cmd_name,
                    "file": rel_path,
                    "line": i,
                    "domain": "backend",
                    "ref_count": 0,
                    "status": "active",
                })
                defined_fns[cmd_name] = node_id
            continue

        # --- Autocommands: autocmd Event pattern ... ---
        # Also handles: au Event pattern ..., autocmd BufEnter *.vim ...
        m = re.match(
            r'\s*(?:autocmd|au)\s+(\w+)\s+(\S+)',
            line,
        )
        if m:
            event = m.group(1)
            pattern = m.group(2)
            # Skip augroup names that look like events (e.g. "end")
            if event.lower() not in _VIM_KEYWORDS and event.lower() != 'end':
                node_id = f"{rel_path}:{i}"
                nodes.append({
                    "id": node_id,
                    "type": "autocmd",
                    "name": f"{event} {pattern}",
                    "fn": event,
                    "file": rel_path,
                    "line": i,
                    "domain": "backend",
                    "ref_count": 0,
                    "status": "active",
                    "event": event,
                    "pattern": pattern,
                })
            continue

        # --- Scoped variables: let g:var = ..., let s:var = ..., let b:var = ... ---
        m = re.match(
            r'\s*let\s+([sSgGbBwWtT]:)(\w+)\s*=',
            line,
        )
        if m:
            scope = m.group(1)
            var_name = m.group(2)
            full_var = f"{scope}{var_name}"
            node_id = f"{rel_path}:{i}"
            nodes.append({
                "id": node_id,
                "type": "variable",
                "name": full_var,
                "fn": var_name,
                "file": rel_path,
                "line": i,
                "domain": "backend",
                "ref_count": 0,
                "status": "active",
                "scope": scope,
            })
            continue

        # --- Keymaps: nnoremap <key> ..., vnoremap <key> ..., etc. ---
        m = re.match(
            r'\s*(n|v|i|x|s|o|c|l|t|nore|nmap|vmap|imap|xmap|smap|omap|cmap|lmap|tmap)'
            r'(?:nore)?map!\s+(\S+)\s+',
            line,
        )
        if m:
            mode = m.group(1)
            key = m.group(2)
            node_id = f"{rel_path}:{i}"
            nodes.append({
                "id": node_id,
                "type": "keymap",
                "name": f"{mode}map {key}",
                "fn": f"{mode}map_{key}",
                "file": rel_path,
                "line": i,
                "domain": "backend",
                "ref_count": 0,
                "status": "active",
                "mode": mode,
                "key": key,
            })
            continue

        # Also handle: nnoremap <key> ..., vnoremap <key> ..., etc. (full names)
        m = re.match(
            r'\s*((?:n|v|i|x|s|o|c|l|t)(?:nore)?map)\s+(\S+)\s+',
            line,
        )
        if m:
            mapping_cmd = m.group(1)
            key = m.group(2)
            node_id = f"{rel_path}:{i}"
            nodes.append({
                "id": node_id,
                "type": "keymap",
                "name": f"{mapping_cmd} {key}",
                "fn": f"{mapping_cmd}_{key}",
                "file": rel_path,
                "line": i,
                "domain": "backend",
                "ref_count": 0,
                "status": "active",
                "mode": mapping_cmd,
                "key": key,
            })
            continue

    # ─── Build function body ranges for call-edge attribution ──────
    # VimScript functions end at `endfunction`
    fn_nodes = [n for n in nodes if n["type"] == "function"]
    fn_starts = sorted(fn_nodes, key=lambda n: n["line"])

    for idx, fn_node in enumerate(fn_starts):
        start_line = fn_node["line"]
        # Find the next endfunction after start_line
        end_line = len(lines)
        for j in range(start_line, len(lines)):
            if re.match(r'\s*endfunction!?\s*$', lines[j], re.IGNORECASE):
                end_line = j + 1  # 1-based
                break
        fn_ranges.append((fn_node["id"], fn_node["fn"], start_line, end_line))

    # ─── Pass 2: Extract function calls and references ─────────────

    # Collect function definition line numbers to skip self-matching
    fn_def_lines = {n["line"] for n in nodes if n["type"] == "function"}

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Skip comment lines
        if stripped.startswith('"'):
            continue

        # Skip function definition lines (avoid self-matching)
        if i in fn_def_lines:
            continue

        # Find which function "owns" this line
        owner_node = _find_owner_by_range(fn_ranges, i)

        # Track call targets already matched via 'call' keyword to avoid
        # duplicate edges from the direct-call pattern
        call_targets_on_line: set = set()

        # --- call FuncName() edges ---
        for m in re.finditer(r'\bcall\s+((?:[sSgGbBwWtT]:)?(?:\w+#)*\w+)\s*\(', stripped):
            call_target = m.group(1)
            # Derive short name for matching
            short = call_target
            if ':' in short:
                short = short.split(':', 1)[1]
            if '#' in short:
                short = short.split('#')[-1]
            if short in _VIM_KEYWORDS:
                continue
            call_targets_on_line.add(short)
            if owner_node and short != owner_node.get("fn"):
                edges.append({
                    "from": owner_node["id"],
                    "to_fn": short,
                    "via_call": True,
                })

        # --- Direct function calls: FuncName() without 'call' ---
        for m in re.finditer(r'\b((?:[sSgGbBwWtT]:)?(?:\w+#)*\w+)\s*\(', stripped):
            call_name = m.group(1)
            short = call_name
            if ':' in short:
                short = short.split(':', 1)[1]
            if '#' in short:
                short = short.split('#')[-1]
            # Skip keywords, and skip 'call' itself (handled above)
            if short in _VIM_KEYWORDS or call_name == 'call':
                continue
            # Skip common VimScript builtins
            if short in _VIM_BUILTINS:
                continue
            # Skip if already captured via 'call' keyword on this line
            if short in call_targets_on_line:
                continue
            if owner_node and short != owner_node.get("fn"):
                edges.append({
                    "from": owner_node["id"],
                    "to_fn": short,
                })

        # --- Variable references inside functions ---
        # e.g. g:SomeVar, s:SomeVar — reference to defined variable nodes
        # Skip scoped identifiers that are followed by '(' (function calls)
        for m in re.finditer(r'\b([sSgGbBwWtT]:)(\w+)', stripped):
            scope = m.group(1)
            var_name = m.group(2)
            if var_name in _VIM_KEYWORDS:
                continue
            # Skip if this scoped identifier is a function call (followed by '(')
            after_match = stripped[m.end():m.end() + 2].strip()
            if after_match.startswith('('):
                continue
            # Check if this is on a 'let' definition line (skip self-reference)
            if re.match(r'\s*let\s+', stripped):
                continue
            if owner_node:
                edges.append({
                    "from": owner_node["id"],
                    "to_fn": f"{scope}{var_name}",
                    "via_var_ref": True,
                })

    return {"nodes": nodes, "edges": edges}


# ─── Internal helpers ──────────────────────────────────────────────

# Common VimScript builtins to skip when tracking call edges
_VIM_BUILTINS = frozenset({
    'exists', 'has', 'expand', 'substitute', 'system', 'systemlist',
    'getline', 'setline', 'append', 'search', 'searchpos', 'match',
    'matchstr', 'matchlist', 'matchadd', 'matchdelete', 'submatch',
    'strlen', 'strpart', 'stridx', 'strridx', 'strdisplaywidth',
    'split', 'join', 'tolower', 'toupper', 'tr', 'printf', 'format',
    'type', 'string', 'float2nr', 'nr2float', 'abs', 'ceil', 'floor',
    'round', 'trunc', 'log', 'log10', 'pow', 'sqrt', 'exp', 'cos',
    'sin', 'tan', 'acos', 'asin', 'atan', 'atan2', 'fmod',
    'floor', 'ceil', 'round', 'trunc',
    'fnamemodify', 'simplify', 'resolve', 'pathshorten',
    'isdirectory', 'isabsolute', 'getcwd', 'chdir',
    'readfile', 'writefile', 'filereadable', 'filewritable',
    'getfsize', 'getftime', 'getftype', 'getfontname',
    'glob', 'globpath', 'glob2regpat',
    'input', 'inputlist', 'inputdialog', 'inputsave', 'inputrestore',
    'confirm', 'browse', 'browsedir',
    'bufname', 'bufnr', 'bufwinnr', 'winbufnr', 'winnr',
    'bufexists', 'buflisted', 'bufloaded',
    'win_getid', 'win_gotoid', 'win_findbuf',
    'tabpagebuflist', 'tabpagenr', 'tabpagewinnr',
    'line', 'col', 'virtcol', 'wincol', 'winline', 'winwidth', 'winheight',
    'getpos', 'setpos', 'cursor',
    'foldclosed', 'foldclosedend', 'foldlevel', 'foldtext',
    'maparg', 'mapcheck', 'mapset', 'hasmapto', 'maplist',
    'getreg', 'setreg', 'reg_executing', 'recording',
    'getcmdline', 'getcmdpos', 'setcmdpos', 'getcmdtype',
    'histadd', 'histdel', 'histget', 'histnr',
    'argidx', 'argc', 'arglistid', 'argv',
    'getchar', 'getcharmod', 'getcharstr', 'getcharsearch',
    'feedkeys', 'nvim_feedkeys',
    'mode', 'state', 'getmousepos',
    'timer_start', 'timer_stop', 'timer_pause', 'timer_info',
    'job_start', 'job_stop', 'job_status', 'job_info',
    'ch_open', 'ch_close', 'ch_read', 'ch_readraw', 'ch_sendexpr',
    'ch_sendraw', 'ch_evalexpr', 'ch_evalraw', 'ch_status', 'ch_info',
    'json_encode', 'json_decode',
    'nvim_get_current_line', 'nvim_set_current_line',
    'nvim_command', 'nvim_eval', 'nvim_call_function',
    'nvim_exec', 'nvim_command_output',
    'nvim_get_option', 'nvim_set_option',
    'nvim_get_var', 'nvim_set_var', 'nvim_del_var',
    'nvim_get_vvar', 'nvim_get_option_info',
    'nvim_list_bufs', 'nvim_list_wins', 'nvim_list_tabpages',
    'nvim_get_current_buf', 'nvim_set_current_buf',
    'nvim_get_current_win', 'nvim_set_current_win',
    'nvim_buf_get_lines', 'nvim_buf_set_lines',
    'nvim_buf_get_text', 'nvim_buf_set_text',
    'nvim_buf_get_name', 'nvim_buf_set_name',
    'nvim_buf_get_option', 'nvim_buf_set_option',
    'nvim_buf_get_var', 'nvim_buf_set_var',
    'nvim_buf_add_highlight', 'nvim_buf_clear_highlight',
    'nvim_buf_set_keymap', 'nvim_buf_del_keymap',
    'nvim_buf_create_user_command', 'nvim_buf_del_user_command',
    'nvim_win_get_buf', 'nvim_win_set_buf',
    'nvim_win_get_cursor', 'nvim_win_set_cursor',
    'nvim_win_get_height', 'nvim_win_set_height',
    'nvim_win_get_width', 'nvim_win_set_width',
    'nvim_win_get_var', 'nvim_win_set_var',
    'nvim_win_get_option', 'nvim_win_set_option',
    'nvim_win_set_cursor',
    'nvim_create_autocmd', 'nvim_del_autocmd',
    'nvim_create_augroup', 'nvim_del_augroup',
    'nvim_create_user_command', 'nvim_del_user_command',
    'nvim_get_keymap', 'nvim_set_keymap', 'nvim_del_keymap',
    'nvim_get_color_map', 'nvim_get_color_by_name',
    'nvim_get_hl', 'nvim_set_hl',
    'nvim_get_runtime_file', 'nvim_get_proc', 'nvim_get_proc_children',
    'nvim_list_runtime_paths',
    'nvim_open_win', 'nvim_win_close',
    'nvim_buf_create_namespace', 'nvim_buf_del_namespace',
    'nvim_buf_get_extmarks', 'nvim_buf_set_extmark', 'nvim_buf_del_extmark',
    'nvim_buf_get_extmark_by_id',
    'nvim_parse_expression', 'nvim_replace_termcodes',
    'nvim_select_popupmenu_item',
    'nvim_strwidth', 'nvim_get_context', 'nvim_load_context',
    'nvim_input', 'nvim_input_mouse',
    'nvim_notify', 'nvim_echo',
    'nvim_tabpage_get_number', 'nvim_tabpage_list_wins',
    'nvim_tabpage_get_var', 'nvim_tabpage_set_var',
    'nvim_tabpage_get_win', 'nvim_tabpage_is_valid',
})


def _find_owner_by_range(
    fn_ranges: List[tuple], line_num: int
) -> Optional[Dict[str, Any]]:
    """Find the function node that 'owns' a line based on function body ranges.

    fn_ranges is a list of (node_id, fn_short_name, start_line, end_line) tuples.
    Returns a minimal dict with 'id' and 'fn' of the owner, or None.
    """
    for node_id, fn_name, start, end in fn_ranges:
        if start <= line_num <= end:
            return {"id": node_id, "fn": fn_name}
    return None


def _find_owner_node(nodes: List[Dict], line_num: int) -> Optional[Dict]:
    """Find the nearest preceding function node that 'owns' a line.

    Fallback method used when fn_ranges is not available.
    """
    best = None
    for node in nodes:
        if node.get("line", 0) <= line_num and node.get("type") == "function":
            if best is None or node["line"] > best["line"]:
                best = node
    return best
