#!/usr/bin/env python3
"""Script to catalog basedpyright type errors from the output file."""

import re
from collections import defaultdict
from pathlib import Path

def parse_basedpyright_output(filepath):
    """Parse basedpyright output and categorize errors."""
    with open(filepath, 'r') as f:
        content = f.read()

    # Extract summary line
    summary_match = re.search(r'(\d+) errors?, (\d+) warnings?, (\d+) notes?', content)
    if summary_match:
        errors_count = int(summary_match.group(1))
        warnings_count = int(summary_match.group(2))
        notes_count = int(summary_match.group(3))
    else:
        errors_count = warnings_count = notes_count = 0

    # Parse individual issues
    # Pattern: file:line:col - severity: message (code)
    pattern = r'(/[^\n]+?):(\d+):(\d+) - (error|warning|note): ([^\n]+)'
    matches = re.findall(pattern, content)

    # Categorize by error code
    by_code = defaultdict(list)
    by_file = defaultdict(list)
    by_severity = defaultdict(list)

    for filepath, line, col, severity, message in matches:
        # Extract error code from message
        code_match = re.search(r'\((\w+)\)$', message)
        code = code_match.group(1) if code_match else 'unknown'

        issue = {
            'file': filepath,
            'line': int(line),
            'col': int(col),
            'severity': severity,
            'message': message,
            'code': code
        }

        by_code[code].append(issue)
        by_file[filepath].append(issue)
        by_severity[severity].append(issue)

    return {
        'summary': {
            'errors': errors_count,
            'warnings': warnings_count,
            'notes': notes_count,
            'total': errors_count + warnings_count + notes_count
        },
        'by_code': dict(by_code),
        'by_file': dict(by_file),
        'by_severity': dict(by_severity)
    }

def generate_catalog_markdown(data):
    """Generate a markdown catalog of type errors."""
    md = []
    md.append("# Basedpyright Type Error Catalog\n")
    md.append(f"**Generated:** {Path(__file__).stat().st_mtime}\n")

    # Summary
    summary = data['summary']
    md.append("## Summary\n")
    md.append(f"- **Errors:** {summary['errors']}")
    md.append(f"- **Warnings:** {summary['warnings']}")
    md.append(f"- **Notes:** {summary['notes']}")
    md.append(f"- **Total Issues:** {summary['total']}\n")

    # By Error Code
    md.append("## Issues by Error Code\n")
    by_code = data['by_code']
    sorted_codes = sorted(by_code.items(), key=lambda x: len(x[1]), reverse=True)

    for code, issues in sorted_codes:
        md.append(f"### {code} ({len(issues)} occurrences)\n")

        # Get a sample message
        sample_msg = issues[0]['message']
        md.append(f"**Example:** {sample_msg}\n")

        # Count by severity
        severity_count = defaultdict(int)
        for issue in issues:
            severity_count[issue['severity']] += 1

        severity_str = ", ".join([f"{sev}: {count}" for sev, count in severity_count.items()])
        md.append(f"**Severity breakdown:** {severity_str}\n")

        # Show top affected files
        file_count = defaultdict(int)
        for issue in issues:
            file_count[issue['file']] += 1

        top_files = sorted(file_count.items(), key=lambda x: x[1], reverse=True)[:5]
        md.append("**Top affected files:**")
        for filepath, count in top_files:
            filename = Path(filepath).name
            md.append(f"  - `{filename}`: {count} occurrences")
        md.append("")

    # By File
    md.append("## Issues by File\n")
    by_file = data['by_file']
    sorted_files = sorted(by_file.items(), key=lambda x: len(x[1]), reverse=True)

    for filepath, issues in sorted_files:
        filename = Path(filepath).relative_to('/home/user/flowno')
        error_count = sum(1 for i in issues if i['severity'] == 'error')
        warning_count = sum(1 for i in issues if i['severity'] == 'warning')

        md.append(f"### {filename}")
        md.append(f"**Total issues:** {len(issues)} (Errors: {error_count}, Warnings: {warning_count})\n")

        # Group by error code
        codes = defaultdict(int)
        for issue in issues:
            codes[issue['code']] += 1

        md.append("**Error codes:**")
        for code, count in sorted(codes.items(), key=lambda x: x[1], reverse=True):
            md.append(f"  - `{code}`: {count}")
        md.append("")

    return "\n".join(md)

if __name__ == '__main__':
    data = parse_basedpyright_output('basedpyright_output.txt')
    catalog = generate_catalog_markdown(data)

    with open('TYPE_ERRORS_CATALOG.md', 'w') as f:
        f.write(catalog)

    print(f"Catalog generated: TYPE_ERRORS_CATALOG.md")
    print(f"Total issues: {data['summary']['total']}")
    print(f"  - Errors: {data['summary']['errors']}")
    print(f"  - Warnings: {data['summary']['warnings']}")
    print(f"  - Notes: {data['summary']['notes']}")
