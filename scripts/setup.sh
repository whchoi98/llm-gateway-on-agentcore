#!/bin/bash
# Project setup script for new developers.
# Usage: bash scripts/setup.sh

set -e

echo "=== Project Setup ==="

# Check prerequisites
command -v git >/dev/null 2>&1 || { echo "ERROR: git is required"; exit 1; }
command -v node >/dev/null 2>&1 || { echo "ERROR: Node.js 22+ is required (AWS CDK app)"; exit 1; }
command -v aws >/dev/null 2>&1 || { echo "ERROR: AWS CLI v2 is required (deploy and scripts/set-cponaws-key.sh)"; exit 1; }
command -v uv >/dev/null 2>&1 || echo "WARNING: uv not found; scripts/smoke_test.py runs with uv (https://docs.astral.sh/uv/)"

# Detect project type and install dependencies
if [ -f "package.json" ]; then
    echo "Installing Node.js dependencies..."
    if command -v pnpm >/dev/null 2>&1; then
        pnpm install
    elif command -v yarn >/dev/null 2>&1; then
        yarn install
    else
        npm install
    fi
elif [ -f "pyproject.toml" ]; then
    echo "Installing Python dependencies..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev]"
elif [ -f "go.mod" ]; then
    echo "Installing Go dependencies..."
    go mod download
elif [ -f "Cargo.toml" ]; then
    echo "Installing Rust dependencies..."
    cargo build
fi

# Setup environment
if [ -f ".env.example" ] && [ ! -f ".env" ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "IMPORTANT: Edit .env with your actual values"
fi

# Setup Claude Code hooks
if [ -f ".claude/hooks/check-doc-sync.sh" ]; then
    chmod +x .claude/hooks/*.sh
    echo "Claude hooks configured"
fi

# Install the commit-msg hook. `git rev-parse` also finds a linked worktree, where .git is a file.
# A hook manager (core.hooksPath) makes install-hooks.sh print the line to add instead; setup goes on.
if git rev-parse --git-dir >/dev/null 2>&1 && [ -f "scripts/install-hooks.sh" ]; then
    bash scripts/install-hooks.sh || echo "WARNING: commit-msg hook not installed; see the message above"
fi

echo "=== Setup Complete ==="
echo "Next steps:"
echo "  1. Edit .env with your configuration"
echo "  2. Read CLAUDE.md for project conventions"
echo "  3. Read docs/onboarding.md for development workflow"
