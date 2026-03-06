#!/usr/bin/env python3
"""
安全审计脚本 - Security Audit Script

扫描代码库中的安全风险：
1. 硬编码密钥检测
2. .gitignore 配置检查
3. 环境变量使用审计
4. CI/CD 集成支持

生成报告：security/audit_report_YYYY-MM-DD.txt
"""

import os
import re
import sys
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Set, Optional
import argparse

# ============================
# 配置常量
# ============================

# 项目根目录 (脚本所在目录的上级)
PROJECT_ROOT = Path(__file__).parent.parent

# 扫描的文件扩展名
SCAN_EXTENSIONS = {'.py', '.js', '.ts', '.java', '.go', '.rb', '.php', '.sh', '.yml', '.yaml', '.json', '.toml', '.cfg', '.ini', '.conf'}

# 忽略的目录/文件模式
IGNORE_PATTERNS = [
    '.git',
    '.github',
    'node_modules',
    'venv',
    'env',
    '.venv',
    '__pycache__',
    'dist',
    'build',
    'target',
    '.idea',
    '.vscode',
    'test_',
    'example_',
    'tests',
    'examples',
    'docs',
    'security',  # 不扫描安全报告目录本身
]

# 硬编码密钥检测正则
SECRET_PATTERNS = [
    # API Keys
    (re.compile(r'(?i)(api[_-]?key|apikey)\s*[=:]\s*[\'"]?([a-zA-Z0-9]{20,})[\'"]?'), 'API Key'),
    (re.compile(r'(?i)(sk|pk)_([a-zA-Z0-9]{20,})'), 'Stripe Key'),
    (re.compile(r'(?i)sk-([a-zA-Z0-9]{24,})'), 'OpenAI/Step API Key'),
    
    # Authorization Tokens
    (re.compile(r'(?i)(auth|authorization)\s*[=:]\s*[\'"]?(Bearer\s+)?([a-zA-Z0-9_\-\.]{20,})[\'"]?'), 'Auth Token'),
    (re.compile(r'(?i)(access[_-]?token|refresh[_-]?token)\s*[=:]\s*[\'"]?([a-zA-Z0-9_\-\.]{20,})[\'"]?'), 'Access/Refresh Token'),
    
    # Secrets
    (re.compile(r'(?i)secret\s*[=:]\s*[\'"]?([a-zA-Z0-9_\-\.]{16,})[\'"]?'), 'Secret'),
    (re.compile(r'(?i)password\s*[=:]\s*[\'"]?([^\'"\s]{6,})[\'"]?'), 'Password'),
    
    # General Keys
    (re.compile(r'(?i)key\s*[=:]\s*[\'"]?([a-zA-Z0-9_\-\.]{20,})[\'"]?'), 'Generic Key'),
    (re.compile(r'(?i)token\s*[=:]\s*[\'"]?([a-zA-Z0-9_\-\.]{20,})[\'"]?'), 'Generic Token'),
    (re.compile(r'(?i)pass\s*[=:]\s*[\'"]?([^\'"\s]{6,})[\'"]?'), 'Password (short)'),
    
    # AWS/Cloud specific
    (re.compile(r'(?i)(aws|aws_access|aws_secret|AKIA)[A-Z0-9]{16,}'), 'AWS Credential'),
    (re.compile(r'(?i)ghp_[a-zA-Z0-9]{36,}'), 'GitHub Personal Access Token'),
    (re.compile(r'(?i)gho_[a-zA-Z0-9]{36,}'), 'GitHub OAuth Token'),
    (re.compile(r'(?i)ghu_[a-zA-Z0-9]{36,}'), 'GitHub User Token'),
    (re.compile(r'(?i)ghs_[a-zA-Z0-9]{36,}'), 'GitHub Secret Scanning Token'),
    (re.compile(r'(?i)ghr_[a-zA-Z0-9]{36,}'), 'GitHub Refresh Token'),
    
    # Database
    (re.compile(r'(?i)(db|database|mysql|postgres|mongodb)://[^\s\'"]+'), 'Database Connection String'),
    (re.compile(r'(?i)jdbc:[a-z]+://[^\s\'"]+'), 'JDBC Connection String'),
    
    # Private Keys
    (re.compile(r'-----BEGIN (RSA )?PRIVATE KEY-----'), 'Private Key'),
    (re.compile(r'-----BEGIN DSA PRIVATE KEY-----'), 'DSA Private Key'),
    (re.compile(r'-----BEGIN EC PRIVATE KEY-----'), 'EC Private Key'),
    (re.compile(r'-----BEGIN OPENSSH PRIVATE KEY-----'), 'OpenSSH Private Key'),
    
    # OAuth
    (re.compile(r'(?i)client_id\s*[=:]\s*[\'"][a-zA-Z0-9_\-\.]{20,}[\'"]'), 'OAuth Client ID'),
    (re.compile(r'(?i)client_secret\s*[=:]\s*[\'"]?([a-zA-Z0-9_\-\.]{16,})[\'"]?'), 'OAuth Client Secret'),
    
    # JWT (simplified pattern)
    (re.compile(r'eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+'), 'JWT Token'),
]

# 忽略的假阳性关键词 (这些词附近的内容我们忽略)
FALSE_POSITIVE_INDICATORS = [
    'example',
    'sample',
    'test',
    'dummy',
    'placeholder',
    'change_me',
    'your_',
    'insert_',
    'replace_',
    'XXX',
    'TODO',
    'FIXME',
]

# ============================
# 辅助函数
# ============================

def should_ignore_path(path: Path) -> bool:
    """检查路径是否应被忽略"""
    path_str = str(path).lower()
    
    for pattern in IGNORE_PATTERNS:
        if pattern.startswith('.') and pattern in path_str:
            return True
        if path.name.startswith(pattern.rstrip('_')):
            return True
        if pattern in path_str:
            return True
    
    return False

def is_likely_false_positive(line: str, match_content: str) -> bool:
    """判断是否可能是误报"""
    line_lower = line.lower()
    
    # 检查是否包含误报指示词
    for indicator in FALSE_POSITIVE_INDICATORS:
        if indicator in line_lower:
            return True
    
    # 检查是否在注释中
    if line.strip().startswith('#'):
        return True
    
    # 检查是否在字符串字面量中且明显是示例 (如包含 "example" 或 "sample")
    if 'example' in line_lower or 'sample' in line_lower:
        return True
    
    # 检查是否在文档字符串或注释块
    if '"""' in line or "'''" in line:
        return True
    
    return False

def assess_risk_level(secret_type: str, line_content: str, file_ext: str) -> str:
    """评估风险等级"""
    high_risk_keywords = ['private key', 'jwt', 'github token', 'aws credential', 'database://', 'jdbc:']
    medium_risk_keywords = ['secret', 'password', 'auth', 'token']
    
    # 如果是私有密钥格式
    if 'BEGIN' in secret_type and 'PRIVATE KEY' in secret_type:
        return 'CRITICAL'
    
    # 检查高风险关键词
    for keyword in high_risk_keywords:
        if keyword in secret_type.lower() or keyword in line_content.lower():
            return 'HIGH'
    
    # 检查中风险关键词
    for keyword in medium_risk_keywords:
        if keyword in secret_type.lower():
            return 'MEDIUM'
    
    # 如果是配置文件且包含密钥
    if file_ext in ['.json', '.yaml', '.yml', '.toml', '.env']:
        return 'MEDIUM'
    
    return 'LOW'

# ============================
# 扫描功能
# ============================

def scan_hardcoded_secrets(project_root: Path) -> List[Dict]:
    """扫描硬编码的密钥"""
    findings = []
    
    print(f"[*] 扫描硬编码密钥...")
    
    for root, dirs, files in os.walk(project_root):
        # 修改 dirs 原地以跳过忽略的目录
        dirs[:] = [d for d in dirs if not should_ignore_path(Path(root) / d)]
        
        for file in files:
            filepath = Path(root) / file
            
            # 跳过非文本文件
            if filepath.suffix not in SCAN_EXTENSIONS:
                continue
            
            # 跳过忽略的文件
            if should_ignore_path(filepath):
                continue
            
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
            except Exception as e:
                findings.append({
                    'type': 'ERROR',
                    'file': str(filepath.relative_to(project_root)),
                    'line': 0,
                    'content': f'无法读取文件: {e}',
                    'risk_level': 'INFO'
                })
                continue
            
            for line_num, line in enumerate(lines, 1):
                for pattern, secret_type in SECRET_PATTERNS:
                    matches = pattern.findall(line)
                    if matches:
                        # 检查是否可能是误报
                        if is_likely_false_positive(line, str(matches[0])):
                            continue
                        
                        for match in matches:
                            findings.append({
                                'type': secret_type,
                                'file': str(filepath.relative_to(project_root)),
                                'line': line_num,
                                'content': line.strip(),
                                'risk_level': assess_risk_level(secret_type, line, filepath.suffix)
                            })
    
    return findings

def check_gitignore(project_root: Path) -> List[Dict]:
    """检查 .gitignore 配置"""
    findings = []
    gitignore_path = project_root / '.gitignore'
    
    print(f"[*] 检查 .gitignore 配置...")
    
    required_ignores = [
        '.env',
        'credentials.json',
        'secrets/',
        '.env.*',
        '*.pem',
        '*.key',
        '*.secret',
    ]
    
    if not gitignore_path.exists():
        findings.append({
            'type': 'MISSING_GITIGNORE',
            'file': '.gitignore',
            'line': 0,
            'content': '未找到 .gitignore 文件',
            'risk_level': 'HIGH',
            'suggestion': '创建 .gitignore 文件并添加敏感文件规则'
        })
        return findings
    
    try:
        with open(gitignore_path, 'r', encoding='utf-8') as f:
            gitignore_content = f.read()
            gitignore_lines = gitignore_content.split('\n')
    except Exception as e:
        findings.append({
            'type': 'ERROR',
            'file': '.gitignore',
            'line': 0,
            'content': f'无法读取 .gitignore: {e}',
            'risk_level': 'INFO'
        })
        return findings
    
    missing_patterns = []
    for pattern in required_ignores:
        # 简单的模式匹配 (实际应该更精确,但够用)
        pattern_found = False
        for line in gitignore_lines:
            line = line.strip()
            if line and not line.startswith('#'):
                # 检查模式是否匹配 (支持简单通配符)
                if pattern.endswith('/'):
                    if line.rstrip('/') == pattern.rstrip('/'):
                        pattern_found = True
                        break
                else:
                    if line == pattern or (pattern.startswith('*.') and line == pattern):
                        pattern_found = True
                        break
                    # 检查前缀匹配 (如 .env 匹配 .env.*)
                    if pattern.startswith('.env') and line.startswith('.env'):
                        pattern_found = True
                        break
        
        if not pattern_found:
            missing_patterns.append(pattern)
    
    if missing_patterns:
        findings.append({
            'type': 'GITIGNORE_MISSING',
            'file': '.gitignore',
            'line': 0,
            'content': f'缺少以下敏感文件规则: {", ".join(missing_patterns)}',
            'risk_level': 'MEDIUM',
            'suggestion': f'在 .gitignore 中添加: {chr(10).join(missing_patterns)}'
        })
    else:
        findings.append({
            'type': 'GITIGNORE_OK',
            'file': '.gitignore',
            'line': 0,
            'content': 'Gitignore 配置正确',
            'risk_level': 'INFO'
        })
    
    return findings

def scan_env_variables(project_root: Path) -> List[Dict]:
    """扫描代码中的环境变量使用"""
    findings = []
    env_vars: Dict[str, List[str]] = {}  # var_name -> [files]
    
    print(f"[*] 扫描环境变量使用...")
    
    # 只扫描 Python 文件
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if not should_ignore_path(Path(root) / d)]
        
        for file in files:
            if file.endswith('.py'):
                filepath = Path(root) / file
                
                if should_ignore_path(filepath):
                    continue
                
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                except:
                    continue
                
                # 查找 os.getenv() 调用
                # 正则: os.getenv('VAR') 或 os.getenv("VAR") 或 os.getenv(VAR)
                pattern = re.compile(r'os\.getenv\s*\(\s*[\'"]?([A-Z_][A-Z0-9_]*)[\'"]?\s*(?:,\s*[^)]*)?\)')
                matches = pattern.findall(content)
                
                for var_name in matches:
                    if var_name not in env_vars:
                        env_vars[var_name] = []
                    env_vars[var_name].append(str(filepath.relative_to(project_root)))
    
    # 识别可能敏感的环境变量名
    sensitive_prefixes = ['API', 'KEY', 'SECRET', 'PASSWORD', 'TOKEN', 'CREDENTIAL', 'AUTH', 'PRIVATE']
    
    for var_name, files in sorted(env_vars.items()):
        is_sensitive = any(prefix in var_name for prefix in sensitive_prefixes)
        
        # 只报告敏感的环境变量
        if is_sensitive:
            # 检查 os.getenv() 是否提供了默认值 (简单检查代码是否包含第二个参数)
            # 这里简化处理 - 实际应该解析 AST
            has_default = False
            for file in files:
                filepath = project_root / file
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        for line_num, line in enumerate(f, 1):
                            if f'os.getenv("{var_name}"' in line or f"os.getenv('{var_name}'" in line:
                                # 检查是否有第二个参数
                                if re.search(rf'os\.getenv\s*\(\s*[\'"]{var_name}[\'"]\s*,\s*[^)]+\)', line):
                                    has_default = True
                                    break
                except:
                    pass
            
            risk = 'MEDIUM' if has_default else 'HIGH'
            
            findings.append({
                'type': 'ENV_VAR',
                'variable': var_name,
                'files': list(set(files)),
                'has_default': has_default,
                'risk_level': risk,
                'content': f'环境变量 {var_name} 在 {len(set(files))} 个文件中使用' + ('' if has_default else ' (未设置默认值)')
            })
    
    return findings

def analyze_ci_config(project_root: Path) -> List[Dict]:
    """分析 CI 配置"""
    findings = []
    
    print(f"[*] 分析 CI 配置...")
    
    github_workflows_dir = project_root / '.github' / 'workflows'
    
    if not github_workflows_dir.exists():
        findings.append({
            'type': 'CI_MISSING',
            'file': '.github/workflows',
            'line': 0,
            'content': '未找到 GitHub Actions 工作流配置',
            'risk_level': 'INFO',
            'suggestion': '建议添加 CI/CD 流程包含安全扫描'
        })
        return findings
    
    workflow_files = list(github_workflows_dir.glob('*.yml')) + list(github_workflows_dir.glob('*.yaml'))
    
    if not workflow_files:
        findings.append({
            'type': 'CI_EMPTY',
            'file': '.github/workflows',
            'line': 0,
            'content': '工作流目录存在但无配置文件',
            'risk_level': 'INFO'
        })
        return findings
    
    # 检查是否有安全扫描
    has_security_scan = False
    for wf in workflow_files:
        try:
            with open(wf, 'r', encoding='utf-8') as f:
                content = f.read().lower()
                if 'security' in content or 'audit' in content or 'sast' in content or 'secret' in content:
                    has_security_scan = True
                    break
        except:
            pass
    
    if not has_security_scan:
        findings.append({
            'type': 'CI_NO_SECURITY',
            'file': '.github/workflows',
            'line': 0,
            'content': 'CI 配置中缺少安全扫描步骤',
            'risk_level': 'MEDIUM',
            'suggestion': '在 CI 流程中添加安全审计步骤 (使用本脚本)'
        })
    
    return findings

# ============================
# 报告生成
# ============================

def generate_report(findings: List[Dict], project_root: Path) -> Path:
    """生成安全审计报告"""
    today = datetime.now().strftime('%Y-%m-%d')
    security_dir = project_root / 'security'
    security_dir.mkdir(exist_ok=True)
    
    report_path = security_dir / f'audit_report_{today}.txt'
    
    # 统计
    total_findings = len(findings)
    critical_count = sum(1 for f in findings if f.get('risk_level') == 'CRITICAL')
    high_count = sum(1 for f in findings if f.get('risk_level') == 'HIGH')
    medium_count = sum(1 for f in findings if f.get('risk_level') == 'MEDIUM')
    low_count = sum(1 for f in findings if f.get('risk_level') == 'LOW')
    info_count = sum(1 for f in findings if f.get('risk_level') == 'INFO')
    
    # 分类统计
    by_type: Dict[str, int] = {}
    for f in findings:
        ftype = f.get('type', 'UNKNOWN')
        by_type[ftype] = by_type.get(ftype, 0) + 1
    
    # 生成报告内容
    report_lines = [
        "=" * 80,
        "安全审计报告 - Security Audit Report",
        "=" * 80,
        f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"项目目录: {project_root}",
        f"扫描统计:",
        f"  总计发现: {total_findings}",
        f"  CRITICAL: {critical_count}",
        f"  HIGH: {high_count}",
        f"  MEDIUM: {medium_count}",
        f"  LOW: {low_count}",
        f"  INFO: {info_count}",
        "",
        "详细发现:",
        "=" * 80,
        ""
    ]
    
    # 按风险等级排序: CRITICAL > HIGH > MEDIUM > LOW > INFO
    risk_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3, 'INFO': 4}
    sorted_findings = sorted(findings, key=lambda f: risk_order.get(f.get('risk_level', 'INFO'), 999))
    
    current_risk = None
    for idx, finding in enumerate(sorted_findings, 1):
        risk = finding.get('risk_level', 'INFO')
        
        if risk != current_risk:
            current_risk = risk
            report_lines.extend([
                f"--- {risk} 风险等级 ---",
                ""
            ])
        
        report_lines.append(f"[{idx}] {finding.get('type', 'UNKNOWN')}")
        
        if 'file' in finding:
            report_lines.append(f"文件: {finding['file']}")
        if 'line' in finding and finding['line'] > 0:
            report_lines.append(f"行号: {finding['line']}")
        if 'variable' in finding:
            report_lines.append(f"变量: {finding['variable']}")
        
        report_lines.append(f"描述: {finding.get('content', '无描述')}")
        
        if 'suggestion' in finding:
            report_lines.append(f"修复建议: {finding['suggestion']}")
        
        report_lines.append("")
    
    # 汇总和建议
    report_lines.extend([
        "=" * 80,
        "总结与建议",
        "=" * 80,
        "",
        f"本次扫描发现 {total_findings} 个安全问题:",
        f"  - CRITICAL: {critical_count} (需立即修复)",
        f"  - HIGH: {high_count} (高优先级)",
        f"  - MEDIUM: {medium_count} (建议修复)",
        f"  - LOW: {low_count} (低优先级)",
        "",
        "修复优先级:",
        "1. CRITICAL - 立即修复,防止密钥泄露",
        "2. HIGH - 尽快修复,防止安全风险",
        "3. MEDIUM - 在下一个迭代中修复",
        "4. LOW - 可择机优化",
        "",
        "建议措施:",
        "- 使用环境变量或密钥管理服务 (如AWS Secrets Manager, Vault) 替代硬编码",
        "- 确保 .env 文件在 .gitignore 中",
        "- 为新服务生成独立的密钥,定期轮换",
        "- 使用预提交钩子 (pre-commit) 扫描敏感信息",
        "- 在 CI/CD 中集成安全扫描并阻塞高风险发现",
        "",
        "=" * 80
    ])
    
    # 写入文件
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report_lines))
    
    print(f"[+] 报告已生成: {report_path}")
    return report_path

# ============================
# GitHub Actions 配置
# ============================

def generate_github_actions_config() -> str:
    """生成 GitHub Actions 工作流配置"""
    workflow_content = """name: Security Audit

on:
  pull_request:
    branches: [ main, develop ]
    paths-ignore:
      - '**.md'
      - '**.txt'
      - 'docs/**'
  push:
    branches: [ main ]

permissions:
  contents: read

jobs:
  security-audit:
    runs-on: ubuntu-latest
    
    steps:
    - name: Checkout code
      uses: actions/checkout@v4
      with:
        fetch-depth: 0  # 获取完整历史以检测敏感信息
    
    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.11'
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
    
    - name: Run security audit
      run: |
        chmod +x scripts/security_audit.py
        python scripts/security_audit.py --fail-on-high
    
    - name: Upload audit report
      if: always()
      uses: actions/upload-artifact@v4
      with:
        name: security-audit-report
        path: security/audit_report_*.txt
    
    - name: Comment PR with findings
      if: github.event_name == 'pull_request'
      run: |
        REPORT=$(ls security/audit_report_*.txt 2>/dev/null || echo "")
        if [ -n "$REPORT" ]; then
          # 提取摘要
          SUMMARY=$(grep -A 10 "总结与建议" "$REPORT" | head -n 15)
          
          # 检测是否有高风险
          if grep -q "CRITICAL\|HIGH" <<< "$SUMMARY"; then
            echo "::error::发现高风险安全问题,请查看详细报告"
            echo "发现高风险安全问题!" 
            echo "\\n\`\`\`"
            echo "$SUMMARY"
            echo "\`\`\`"
          else
            echo "::notice::未发现高风险安全问题"
            echo "✅ 安全扫描通过"
          fi
        fi
"""
    return workflow_content

def write_github_actions_config(project_root: Path) -> Path:
    """写入 GitHub Actions 配置文件"""
    workflows_dir = project_root / '.github' / 'workflows'
    workflows_dir.mkdir(parents=True, exist_ok=True)
    
    workflow_path = workflows_dir / 'security-audit.yml'
    
    content = generate_github_actions_config()
    
    with open(workflow_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"[+] GitHub Actions 配置已生成: {workflow_path}")
    return workflow_path

# ============================
# 主程序
# ============================

def main():
    parser = argparse.ArgumentParser(description='安全审计脚本')
    parser.add_argument('--path', type=str, default=str(PROJECT_ROOT),
                        help='扫描的根目录 (默认: 项目根目录)')
    parser.add_argument('--output', type=str,
                        help='自定义报告输出路径')
    parser.add_argument('--fail-on-high', action='store_true',
                        help='发现高风险问题时返回非零退出码 (用于CI)')
    parser.add_argument('--skip-ci', action='store_true',
                        help='跳过 CI 配置生成')
    
    args = parser.parse_args()
    
    project_root = Path(args.path).resolve()
    
    print("=" * 80)
    print("安全审计脚本 - Security Audit")
    print(f"项目目录: {project_root}")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    print()
    
    # 执行所有扫描
    all_findings = []
    
    # 1. 硬编码密钥扫描
    secret_findings = scan_hardcoded_secrets(project_root)
    all_findings.extend(secret_findings)
    print(f"[+] 硬编码密钥扫描完成: {len(secret_findings)} 个发现")
    
    # 2. .gitignore 检查
    gitignore_findings = check_gitignore(project_root)
    all_findings.extend(gitignore_findings)
    print(f"[+] .gitignore 检查完成: {len(gitignore_findings)} 个发现")
    
    # 3. 环境变量审计
    env_findings = scan_env_variables(project_root)
    all_findings.extend(env_findings)
    print(f"[+] 环境变量审计完成: {len(env_findings)} 个发现")
    
    # 4. CI 配置分析
    ci_findings = analyze_ci_config(project_root)
    all_findings.extend(ci_findings)
    print(f"[+] CI 配置分析完成: {len(ci_findings)} 个发现")
    
    print()
    print("=" * 80)
    print(f"扫描完成! 总计发现 {len(all_findings)} 个问题")
    
    # 按等级统计
    for level in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']:
        count = sum(1 for f in all_findings if f.get('risk_level') == level)
        if count > 0:
            print(f"  {level}: {count}")
    
    print("=" * 80)
    print()
    
    # 生成报告
    report_path = args.output if args.output else None
    if not report_path:
        report_path = generate_report(all_findings, project_root)
    else:
        # 确保输出目录存在
        output_path = Path(report_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 临时生成报告内容
        temp_report = generate_report(all_findings, project_root)
        # 复制到指定位置
        with open(temp_report, 'r', encoding='utf-8') as src:
            with open(output_path, 'w', encoding='utf-8') as dst:
                dst.write(src.read())
        print(f"[+] 报告已保存到: {output_path}")
    
    # 生成 GitHub Actions 配置 (如果需要)
    if not args.skip_ci:
        try:
            write_github_actions_config(project_root)
        except Exception as e:
            print(f"[!] 生成 GitHub Actions 配置失败: {e}")
    
    # 根据 --fail-on-high 参数决定退出码
    if args.fail_on_high:
        high_or_critical = sum(1 for f in all_findings 
                              if f.get('risk_level') in ['CRITICAL', 'HIGH'])
        if high_or_critical > 0:
            print(f"[!] 发现 {high_or_critical} 个高风险问题,退出码 1")
            return 1
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
