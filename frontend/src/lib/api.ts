const API_BASE_URL = "";

type ApiRequestOptions = Omit<RequestInit, "body"> & {
  body?: BodyInit | FormData | Record<string, unknown> | null;
};

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function buildUrl(path: string) {
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const { body, ...rest } = options;

  let resolvedBody: BodyInit | null | undefined = null;
  if (body instanceof FormData) {
    resolvedBody = body;
  } else if (body && typeof body === "object") {
    headers.set("Content-Type", "application/json");
    resolvedBody = JSON.stringify(body);
  } else if (typeof body === "string") {
    resolvedBody = body;
  } else {
    resolvedBody = body ?? null;
  }

  const response = await fetch(buildUrl(path), {
    ...rest,
    body: resolvedBody,
    headers,
    credentials: "include"
  });

  const contentType = response.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");
  const payload = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    const detail =
      typeof payload === "object" && payload && "detail" in payload
        ? String(payload.detail)
        : typeof payload === "string" && payload
          ? payload
          : `Request failed with status ${response.status}`;
    throw new ApiError(detail, response.status);
  }

  return payload as T;
}

export async function deleteRequest<T>(path: string) {
  return apiRequest<T>(path, { method: "DELETE" });
}

export { API_BASE_URL };
