/* Geomas side of the postMessage bridge with the GIS data portal iframe.
 *
 * Messages are {v: 1, type, ...}:
 *   portal -> Geomas   gis-portal:hello, gis-portal:ticket-request {nonce},
 *                      gis-portal:show, gis-portal:status {linked, userName}
 *   Geomas -> portal   gis-portal:ticket {nonce, ticket}, gis-portal:context {chatId},
 *                      gis-portal:visibility {visible}, gis-portal:navigate {hash},
 *                      gis-portal:theme {mode}
 *
 * A ticket lets its holder take the assistant's commands and answer its
 * confirmation requests in the user's name, so it goes only to the portal's
 * origin, and only messages from that very iframe are listened to. */

import { GIS_PORTAL_URL, WEBUI_API_BASE_URL } from '$lib/constants';

export const MESSAGE_VERSION = 1;

export function portalOrigin(url: string = GIS_PORTAL_URL): string {
	try {
		return new URL(url).origin;
	} catch {
		return '';
	}
}

export const PORTAL_ORIGIN = portalOrigin();

export interface PortalMessage {
	v: number;
	type: string;
	[key: string]: unknown;
}

/** A message from our portal iframe - not from another frame or site. */
export function isPortalMessage(
	event: Pick<MessageEvent, 'origin' | 'source' | 'data'>,
	frame: Pick<HTMLIFrameElement, 'contentWindow'> | null,
	origin: string = PORTAL_ORIGIN
): event is MessageEvent<PortalMessage> {
	const data = event.data;
	return Boolean(
		frame &&
		origin &&
		event.origin === origin &&
		event.source === frame.contentWindow &&
		data &&
		typeof data === 'object' &&
		data.v === MESSAGE_VERSION &&
		typeof data.type === 'string'
	);
}

export function postToPortal(
	frame: Pick<HTMLIFrameElement, 'contentWindow'> | null,
	type: string,
	payload: Record<string, unknown> = {},
	origin: string = PORTAL_ORIGIN
): void {
	if (!frame?.contentWindow || !origin) return;
	frame.contentWindow.postMessage({ v: MESSAGE_VERSION, type, ...payload }, origin);
}

/** A fresh ticket for the signed-in user, or null (not configured, not a session). */
export async function fetchTicket(
	token: string | null = localStorage.token ?? null
): Promise<string | null> {
	if (!token) return null;
	try {
		const response = await fetch(`${WEBUI_API_BASE_URL}/gis-portal/ticket`, {
			headers: { Authorization: `Bearer ${token}` }
		});
		if (!response.ok) return null;
		const body = await response.json();
		return typeof body?.ticket === 'string' ? body.ticket : null;
	} catch {
		return null;
	}
}
