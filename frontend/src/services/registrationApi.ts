import { useQuery } from '@tanstack/react-query';

import { apiClient } from './apiClient';

export interface RegistrationInfo {
  enabled: boolean;
  /** Empty = any address. */
  email_domains: string[];
}

export const fetchRegistrationInfo = async (): Promise<RegistrationInfo> => {
  const res = await apiClient.get<RegistrationInfo>('/api/v1/auth/registration');
  return res.data;
};

/** Whether self sign-up is open. While loading, or if the server can't say, this is
 *  undefined: callers should then keep offering sign-up and let the server decide. */
export const useRegistrationInfo = () =>
  useQuery({
    queryKey: ['registration-info'],
    queryFn: fetchRegistrationInfo,
    staleTime: 5 * 60 * 1000,
    retry: false,
  }).data;
