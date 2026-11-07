import { QueryClientProvider } from '@tanstack/react-query';
import { createRoot } from 'react-dom/client';
import { queryClient } from '../../src/lib/queryClient';
import Fixture from './room';

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={queryClient}>
    <Fixture />
  </QueryClientProvider>,
);
