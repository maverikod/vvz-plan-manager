# Block ID: cas-research

Server:
- `code-analysis-server-vvz`

Use for:
- Research and inspection on project code

Confirmed command group:
- `list_projects`, `list_project_files`
- `search`, `search_get_status`, `search_get_page`, `search_close`
- `universal_file_preview`
- `file_structure`, `list_code_entities`, `get_code_entity_info`
- `find_usages`, `find_dependencies`, `find_classes`
- `get_imports`, `get_ast`, `search_ast_nodes`
- `analyze_tree`, `analyze_complexity`, `comprehensive_analysis`
- `get_file_lines` only for invalid syntax / raw line range fallback

Confirmed laws:
- Research and inspection belong to CAS
- Generic discovery uses `search`
- Structural preview uses identifier drill-down
- Line-addressing on healthy structured files is not the normal path
