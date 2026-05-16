'use client';

/**
 * 工作流编辑器页面 /dashboard/canvas/[id]
 * 三栏布局：左 NodePalette + 中 Canvas + 右 ConfigPanel
 * 底部：IssueList 占位
 *
 * ?mock=1 时使用 localStorage 模拟 API（Plan 02-08 前的离线体验）
 */

import { use, useCallback, useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeftIcon, SaveIcon, RocketIcon } from 'lucide-react';
import { toast } from 'sonner';
import type { ReactFlowInstance } from '@xyflow/react';

import { Canvas } from '@/components/agent-builder/canvas/canvas';
import { NodePalette } from '@/components/agent-builder/canvas/panels/node-palette';
import { ConfigPanel } from '@/components/agent-builder/canvas/panels/config-panel';
import { IssueList } from '@/components/agent-builder/canvas/panels/issue-list';
import { RunInstanceDialog } from '@/components/agent-builder/instances/run-instance-dialog';
import { useCanvasStore } from '@/lib/stores/canvas-store';
import { useValidatorStore } from '@/lib/stores/validator-store';
import { useDebouncedValidator } from '@/lib/hooks/use-debounced-validator';
import { workflowsApi } from '@/lib/api/workflows';
import type { DSL } from '@/lib/types/dsl';

interface PageParams {
  id: string;
}

/** 从 localStorage 获取 mock DSL */
function getMockDSL(id: string): DSL | null {
  try {
    const raw = localStorage.getItem(`agent_builder:mock_dsl:${id}`);
    return raw ? (JSON.parse(raw) as DSL) : null;
  } catch {
    return null;
  }
}

/** 保存 mock DSL 到 localStorage */
function saveMockDSL(id: string, dsl: DSL): void {
  try {
    localStorage.setItem(`agent_builder:mock_dsl:${id}`, JSON.stringify(dsl));
  } catch {
    // localStorage 不可用时静默忽略
  }
}

/** 工作流名称内联编辑 */
function WorkflowNameEditor({
  name,
  onChange,
}: {
  name: string;
  onChange: (v: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setDraft(name);
  }, [name]);

  function startEdit() {
    setEditing(true);
    setTimeout(() => inputRef.current?.select(), 0);
  }

  function commit() {
    setEditing(false);
    const trimmed = draft.trim();
    if (trimmed && trimmed !== name) {
      onChange(trimmed);
    } else {
      setDraft(name);
    }
  }

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
          if (e.key === 'Escape') {
            setEditing(false);
            setDraft(name);
          }
        }}
        className="rounded border border-indigo-400 px-2 py-0.5 text-sm font-semibold text-gray-800 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        autoFocus
      />
    );
  }

  return (
    <button
      onClick={startEdit}
      className="rounded px-1 py-0.5 text-sm font-semibold text-gray-800 hover:bg-gray-100"
      title="点击编辑工作流名称"
    >
      {name}
    </button>
  );
}

export default function WorkflowEditorPage({ params }: { params: Promise<PageParams> }) {
  const { id } = use(params);
  const router = useRouter();
  const searchParams = useSearchParams();
  const isMock = searchParams.get('mock') === '1';

  const [rfInstance, setRfInstance] = useState<ReactFlowInstance | null>(null);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [workflowStatus, setWorkflowStatus] = useState<'draft' | 'published'>('draft');
  const [showRunDialog, setShowRunDialog] = useState(false);
  const [currentDsl, setCurrentDsl] = useState<DSL | null>(null);

  const { workflowName, setWorkflowName, setWorkflowId, loadDSL, exportDSL } =
    useCanvasStore();

  // 300ms 防抖 DSL 实时校验（节点/边变更自动触发）
  useDebouncedValidator(300);

  // 订阅校验状态（控制发布按钮）
  const hasFatalErrors = useValidatorStore((s) => s.hasFatalErrors);

  // 初始化：加载工作流 DSL
  useEffect(() => {
    setWorkflowId(id);

    if (isMock) {
      // mock 模式：从 localStorage 读取或使用空 DSL
      const mockDSL = getMockDSL(id) ?? {
        version: '1.0' as const,
        name: id === 'demo' ? '示例工作流' : `工作流 ${id}`,
        state_schema: {},
        nodes: [],
        edges: [],
      };
      loadDSL(mockDSL);
      return;
    }

    // 正常模式：从 API 加载
    workflowsApi
      .get(id)
      .then((detail) => {
        loadDSL(detail.dsl);
        setWorkflowStatus(detail.status);
        setCurrentDsl(detail.dsl);
      })
      .catch(() => {
        // API 未就绪时降级到 mock 模式（不提示错误，静默降级）
        const mockDSL = getMockDSL(id) ?? {
          version: '1.0' as const,
          name: `工作流 ${id}`,
          state_schema: {},
          nodes: [],
          edges: [],
        };
        loadDSL(mockDSL);
      });
  }, [id, isMock, loadDSL, setWorkflowId]);

  // 保存草稿
  const handleSaveDraft = useCallback(async () => {
    if (saving) return;
    setSaving(true);
    try {
      const dsl = exportDSL();
      if (isMock) {
        saveMockDSL(id, dsl);
        toast.success('草稿已保存（本地）');
        return;
      }
      await workflowsApi.saveDraft(id, dsl);
      toast.success('草稿已保存');
    } catch {
      toast.error('保存失败，请重试');
    } finally {
      setSaving(false);
    }
  }, [id, isMock, saving, exportDSL]);

  // 发布工作流
  const handlePublish = useCallback(async () => {
    if (publishing) return;
    // 有致命错误时阻断发布（前端校验）
    if (hasFatalErrors) {
      toast.error('存在校验错误，请修复后再发布');
      return;
    }
    setPublishing(true);
    try {
      if (isMock) {
        toast.info('发布功能在 Plan 02-08 上线后可用');
        return;
      }
      const dsl = exportDSL();

      // 发布前后端权威复检（CONTEXT.md 决策 #15 两阶段校验）
      try {
        const validateResult = await workflowsApi.validate(dsl);
        if (validateResult?.errors?.some((e: { severity: string }) => e.severity === 'error')) {
          toast.error('后端校验发现错误，请修复后重试');
          return;
        }
      } catch {
        // validate 接口不可用时降级（不阻断发布）
      }

      // 先保存草稿再发布
      await workflowsApi.saveDraft(id, dsl);
      await workflowsApi.publish(id);
      setWorkflowStatus('published');
      toast.success('工作流已发布');
    } catch (e: unknown) {
      const message =
        e instanceof Error ? e.message : '发布失败，请检查 DSL 是否有误';
      toast.error(message);
    } finally {
      setPublishing(false);
    }
  }, [id, isMock, publishing, hasFatalErrors, exportDSL]);

  // 返回列表
  function handleBack() {
    router.push('/dashboard/canvas');
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-gray-50">
      {/* 顶部工具栏 */}
      <header className="flex h-12 flex-shrink-0 items-center justify-between border-b border-gray-200 bg-white px-4">
        <div className="flex items-center gap-3">
          <button
            onClick={handleBack}
            className="rounded p-1 text-gray-500 hover:bg-gray-100"
            title="返回工作流列表"
          >
            <ArrowLeftIcon className="h-4 w-4" />
          </button>

          <WorkflowNameEditor
            name={workflowName}
            onChange={setWorkflowName}
          />

          <span
            className={`rounded px-2 py-0.5 text-xs font-medium ${
              workflowStatus === 'published'
                ? 'bg-green-100 text-green-700'
                : 'bg-yellow-100 text-yellow-700'
            }`}
          >
            {workflowStatus === 'published' ? '已发布' : '草稿'}
          </span>

          {isMock && (
            <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
              本地体验模式
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* 运行工作流 */}
          <button
            onClick={() => setShowRunDialog(true)}
            disabled={workflowStatus !== 'published' || isMock}
            title={
              isMock
                ? '本地模式不支持运行'
                : workflowStatus !== 'published'
                  ? '请先发布工作流'
                  : '运行工作流'
            }
            className="flex items-center gap-1 rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-400"
          >
            <RocketIcon className="h-3.5 w-3.5" />
            运行
          </button>

          {/* 保存草稿 */}
          <button
            onClick={handleSaveDraft}
            disabled={saving}
            className="flex items-center gap-1 rounded-lg border border-indigo-300 px-3 py-1.5 text-sm text-indigo-600 hover:bg-indigo-50 disabled:opacity-60"
          >
            <SaveIcon className="h-3.5 w-3.5" />
            {saving ? '保存中…' : '保存草稿'}
          </button>

          {/* 发布（有致命校验错误时禁用） */}
          <button
            onClick={handlePublish}
            disabled={publishing || hasFatalErrors}
            title={hasFatalErrors ? '存在校验错误，请先修复再发布' : undefined}
            className="flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
            data-testid="publish-btn"
          >
            {publishing ? '发布中…' : hasFatalErrors ? '修复错误后才能发布' : '发布'}
          </button>
        </div>
      </header>

      {/* 三栏主体 */}
      <div className="flex min-h-0 flex-1">
        {/* 左：节点库 */}
        <NodePalette />

        {/* 中：画布 */}
        <div className="min-w-0 flex-1">
          <Canvas onInit={setRfInstance} />
        </div>

        {/* 右：配置面板 */}
        <ConfigPanel />
      </div>

      {/* 底部：Issue 列表 */}
      <IssueList />

      {/* 运行实例弹窗 */}
      {showRunDialog && (
        <RunInstanceDialog
          workflowId={id}
          workflowName={workflowName}
          dsl={currentDsl}
          onClose={() => setShowRunDialog(false)}
        />
      )}
    </div>
  );
}
