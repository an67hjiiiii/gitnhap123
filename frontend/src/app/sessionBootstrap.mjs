export async function bootstrapWorkspace(api, { researchMode = false } = {}) {
  let session;
  try {
    session = await api.currentSession();
  } catch (error) {
    if (error?.status !== 401) throw error;
    const [health] = await Promise.allSettled([api.health()]);
    return {
      authenticated: false,
      sessionExpired: true,
      user: null,
      health,
      sources: null,
      history: null,
      conversations: null,
    };
  }

  if (!session?.authenticated) {
    const [health] = await Promise.allSettled([api.health()]);
    return {
      authenticated: false,
      sessionExpired: false,
      user: null,
      health,
      sources: null,
      history: null,
      conversations: null,
    };
  }

  const [health, sources, navigation] = await Promise.allSettled([
    api.health(),
    api.listSources(),
    researchMode ? api.listRuns() : api.listConversations(),
  ]);
  return {
    authenticated: true,
    sessionExpired: false,
    user: session.user,
    health,
    sources,
    history: researchMode ? navigation : null,
    conversations: researchMode ? null : navigation,
  };
}
