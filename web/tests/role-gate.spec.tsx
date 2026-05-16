/**
 * RoleGate 组件测试
 * 验证 4 角色 × need 组合的渲染逻辑
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RoleGate } from '@/components/auth/role-gate';
import { useUserStore } from '@/lib/stores/user-store';
import type { RoleCode } from '@/lib/types/api';

/** 辅助函数：设置 store 中的角色 */
function setRole(role: RoleCode | null) {
  useUserStore.setState({ role });
}

beforeEach(() => {
  // 每个测试前重置 store
  useUserStore.setState({
    user: null,
    workspaces: [],
    currentWorkspace: null,
    role: null,
  });
});

describe('RoleGate', () => {
  // ===== role=null 时 =====
  it('role=null 时渲染 fallback', () => {
    render(
      <RoleGate need="admin" fallback={<div>无权限</div>}>
        <div>受保护内容</div>
      </RoleGate>,
    );
    expect(screen.getByText('无权限')).toBeInTheDocument();
    expect(screen.queryByText('受保护内容')).not.toBeInTheDocument();
  });

  it('role=null + 无 fallback 时什么都不渲染', () => {
    render(
      <RoleGate need="admin">
        <div>受保护内容</div>
      </RoleGate>,
    );
    expect(screen.queryByText('受保护内容')).not.toBeInTheDocument();
  });

  // ===== super_admin 通过所有 =====
  it('super_admin 通过 need="admin"', () => {
    setRole('super_admin');
    render(
      <RoleGate need="admin" fallback={<div>无权限</div>}>
        <div>受保护内容</div>
      </RoleGate>,
    );
    expect(screen.getByText('受保护内容')).toBeInTheDocument();
  });

  it('super_admin 通过 need="editor"', () => {
    setRole('super_admin');
    render(
      <RoleGate need="editor" fallback={<div>无权限</div>}>
        <div>受保护内容</div>
      </RoleGate>,
    );
    expect(screen.getByText('受保护内容')).toBeInTheDocument();
  });

  it('super_admin 通过 need="viewer"', () => {
    setRole('super_admin');
    render(
      <RoleGate need="viewer" fallback={<div>无权限</div>}>
        <div>受保护内容</div>
      </RoleGate>,
    );
    expect(screen.getByText('受保护内容')).toBeInTheDocument();
  });

  // ===== admin 角色 =====
  it('admin 通过 need="admin"', () => {
    setRole('admin');
    render(
      <RoleGate need="admin" fallback={<div>无权限</div>}>
        <div>受保护内容</div>
      </RoleGate>,
    );
    expect(screen.getByText('受保护内容')).toBeInTheDocument();
  });

  it('admin 通过 need=["admin","editor"]', () => {
    setRole('admin');
    render(
      <RoleGate need={['admin', 'editor']} fallback={<div>无权限</div>}>
        <div>受保护内容</div>
      </RoleGate>,
    );
    expect(screen.getByText('受保护内容')).toBeInTheDocument();
  });

  it('admin 不通过 need="viewer"（viewer 只读，不包含 admin）', () => {
    // 注意：这里验证 need 是精确匹配而非层级
    setRole('viewer');
    render(
      <RoleGate need="admin" fallback={<div>无权限</div>}>
        <div>受保护内容</div>
      </RoleGate>,
    );
    expect(screen.queryByText('受保护内容')).not.toBeInTheDocument();
    expect(screen.getByText('无权限')).toBeInTheDocument();
  });

  // ===== editor 角色 =====
  it('editor 通过 need="editor"', () => {
    setRole('editor');
    render(
      <RoleGate need="editor" fallback={<div>无权限</div>}>
        <div>受保护内容</div>
      </RoleGate>,
    );
    expect(screen.getByText('受保护内容')).toBeInTheDocument();
  });

  it('editor 不通过 need="admin"', () => {
    setRole('editor');
    render(
      <RoleGate need="admin" fallback={<div>无权限</div>}>
        <div>受保护内容</div>
      </RoleGate>,
    );
    expect(screen.queryByText('受保护内容')).not.toBeInTheDocument();
    expect(screen.getByText('无权限')).toBeInTheDocument();
  });

  // ===== viewer 角色 =====
  it('viewer 通过 need="viewer"', () => {
    setRole('viewer');
    render(
      <RoleGate need="viewer" fallback={<div>无权限</div>}>
        <div>受保护内容</div>
      </RoleGate>,
    );
    expect(screen.getByText('受保护内容')).toBeInTheDocument();
  });

  it('viewer 不通过 need="editor"', () => {
    setRole('viewer');
    render(
      <RoleGate need="editor" fallback={<div>无权限</div>}>
        <div>受保护内容</div>
      </RoleGate>,
    );
    expect(screen.queryByText('受保护内容')).not.toBeInTheDocument();
  });

  it('viewer 不通过 need="admin"', () => {
    setRole('viewer');
    render(
      <RoleGate need="admin" fallback={<div>无权限</div>}>
        <div>受保护内容</div>
      </RoleGate>,
    );
    expect(screen.queryByText('受保护内容')).not.toBeInTheDocument();
  });

  // ===== 数组 need =====
  it('need 为数组时满足其一即可渲染', () => {
    setRole('editor');
    render(
      <RoleGate need={['admin', 'editor', 'viewer']} fallback={<div>无权限</div>}>
        <div>受保护内容</div>
      </RoleGate>,
    );
    expect(screen.getByText('受保护内容')).toBeInTheDocument();
  });

  it('need 为数组时不满足任一则渲染 fallback', () => {
    setRole('viewer');
    render(
      <RoleGate need={['admin', 'editor']} fallback={<div>无权限</div>}>
        <div>受保护内容</div>
      </RoleGate>,
    );
    expect(screen.queryByText('受保护内容')).not.toBeInTheDocument();
    expect(screen.getByText('无权限')).toBeInTheDocument();
  });

  // ===== external 角色 =====
  it('external 不通过 need="viewer"', () => {
    setRole('external');
    render(
      <RoleGate need="viewer" fallback={<div>无权限</div>}>
        <div>受保护内容</div>
      </RoleGate>,
    );
    expect(screen.queryByText('受保护内容')).not.toBeInTheDocument();
  });
});
