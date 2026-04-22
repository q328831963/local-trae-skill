import api from './api';
import {
  KnowledgeBase,
  CreateKnowledgeBaseRequest,
  UpdateKnowledgeBaseRequest
} from '../types/knowledge_base';

export interface KBSummary {
  kb_id: string;
  kb_name: string;
  summary: string;
  topics: string[];
  key_content: string;
  document_count: number;
}

export interface KBSummaryInfo {
  kb_id: string;
  kb_name: string;
  summary: string | null;
  summary_updated_at: string | null;
  has_summary: boolean;
}

interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
}

export const knowledgeBaseApi = {
  list: async (): Promise<KnowledgeBase[]> => {
    const response = await api.get<ApiResponse<KnowledgeBase[]>>('/knowledge-bases/');
    return (response as unknown as ApiResponse<KnowledgeBase[]>).data;
  },

  get: async (id: string): Promise<KnowledgeBase> => {
    const response = await api.get<ApiResponse<KnowledgeBase>>(`/knowledge-bases/${id}`);
    return (response as unknown as ApiResponse<KnowledgeBase>).data;
  },

  create: async (data: CreateKnowledgeBaseRequest): Promise<KnowledgeBase> => {
    const response = await api.post<ApiResponse<KnowledgeBase>>('/knowledge-bases/', data);
    return (response as unknown as ApiResponse<KnowledgeBase>).data;
  },

  update: async (id: string, data: UpdateKnowledgeBaseRequest): Promise<KnowledgeBase> => {
    const response = await api.put<ApiResponse<KnowledgeBase>>(`/knowledge-bases/${id}`, data);
    return (response as unknown as ApiResponse<KnowledgeBase>).data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/knowledge-bases/${id}`);
  },

  generateSummary: async (kbId: string): Promise<KBSummary> => {
    const response = await api.post<ApiResponse<KBSummary>>(
      `/knowledge-bases/${kbId}/summary/generate`
    );
    return (response as unknown as ApiResponse<KBSummary>).data;
  },

  getSummary: async (kbId: string): Promise<KBSummaryInfo> => {
    const response = await api.get<ApiResponse<KBSummaryInfo>>(
      `/knowledge-bases/${kbId}/summary`
    );
    return (response as unknown as ApiResponse<KBSummaryInfo>).data;
  },

  regenerateAllSummaries: async (): Promise<any> => {
    const response = await api.post<ApiResponse<any>>(
      '/knowledge-bases/summaries/regenerate-all'
    );
    return (response as unknown as ApiResponse<any>).data;
  },
};
