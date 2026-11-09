import { describe, expect, it, vi } from 'vitest';

import { isPortalMessage, MESSAGE_VERSION, portalOrigin, postToPortal } from './bridge';

const ORIGIN = 'http://87.228.65.110:11111';

function fakeFrame() {
	const contentWindow = { postMessage: vi.fn() };
	return { contentWindow } as unknown as HTMLIFrameElement & {
		contentWindow: { postMessage: ReturnType<typeof vi.fn> };
	};
}

describe('portal origin', () => {
	it('is the origin of the portal page', () => {
		expect(portalOrigin('http://87.228.65.110:11111/ui/portal/')).toBe(ORIGIN);
	});

	it('is empty for a broken setting', () => {
		expect(portalOrigin('')).toBe('');
	});
});

describe('messages from the portal', () => {
	const frame = fakeFrame();
	const message = (overrides: Record<string, unknown> = {}) => ({
		origin: ORIGIN,
		source: frame.contentWindow as unknown as MessageEventSource,
		data: { v: MESSAGE_VERSION, type: 'gis-portal:ticket-request', nonce: 'n' },
		...overrides
	});

	it('are accepted from our iframe', () => {
		expect(isPortalMessage(message(), frame, ORIGIN)).toBe(true);
	});

	it('from another site are ignored', () => {
		expect(isPortalMessage(message({ origin: 'http://evil.example' }), frame, ORIGIN)).toBe(false);
	});

	it('from another frame of the same site are ignored', () => {
		expect(isPortalMessage(message({ source: {} as MessageEventSource }), frame, ORIGIN)).toBe(
			false
		);
	});

	it('of another protocol version are ignored', () => {
		expect(isPortalMessage(message({ data: { v: 2, type: 'x' } }), frame, ORIGIN)).toBe(false);
		expect(isPortalMessage(message({ data: 'gis-portal:show' }), frame, ORIGIN)).toBe(false);
	});
});

describe('messages to the portal', () => {
	it('go only to the portal origin', () => {
		const frame = fakeFrame();
		postToPortal(frame, 'gis-portal:ticket', { nonce: 'n', ticket: 't' }, ORIGIN);
		expect(frame.contentWindow.postMessage).toHaveBeenCalledWith(
			{ v: MESSAGE_VERSION, type: 'gis-portal:ticket', nonce: 'n', ticket: 't' },
			ORIGIN
		);
	});

	it('are not sent without a known origin', () => {
		const frame = fakeFrame();
		postToPortal(frame, 'gis-portal:ticket', { ticket: 't' }, '');
		expect(frame.contentWindow.postMessage).not.toHaveBeenCalled();
	});
});
