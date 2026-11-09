<script lang="ts">
	import { getContext, onDestroy, onMount } from 'svelte';
	import { get } from 'svelte/store';
	import { page } from '$app/stores';

	import { GIS_PORTAL_URL } from '$lib/constants';
	import { chatId, mobile, showSidebar, sidebarWidth } from '$lib/stores';

	import ResizableSidePanel from '$lib/components/common/ResizableSidePanel.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Home from '$lib/components/icons/Home.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	import { fetchTicket, isPortalMessage, postToPortal } from './bridge';
	import { gisPortalLink, gisPortalVisible, showGisPortal } from './stores';

	const i18n: any = getContext('i18n');

	// The portal's share of the room beside the sidebar, kept as a share so it
	// holds when the window or the sidebar changes. 0.7 leaves the chat 30%.
	const RATIO_KEY = 'gisPortalRatio';
	const DEFAULT_RATIO = 0.7;
	const MIN_WIDTH = 320;
	// Narrowest the chat column may get while the portal is widened.
	const MIN_CHAT_WIDTH = 360;
	// Collapsed, the sidebar is an in-flow strip this wide; expanded, it is
	// `position: fixed` and the chat makes room for it with its own max-width.
	const COLLAPSED_SIDEBAR_WIDTH = 42;
	// Resizers whose drag may cross the iframe, which would swallow the pointer.
	const RESIZERS = '#gis-portal-resizer, #controls-resizer, #sidebar-resizer';

	let innerWidth = window.innerWidth;
	// Any resizer drag: the iframe gets an overlay so it cannot swallow the pointer.
	let dragging = false;
	// A drag of this panel's own resizer: ResizableSidePanel owns the width meanwhile.
	let resizingPortal = false;
	let frame: HTMLIFrameElement | null = null;

	// The chat list is expanded beside the portal: on load and whenever the
	// portal is switched on. Collapsing it afterwards is left alone.
	onDestroy(
		showGisPortal.subscribe((shown) => {
			if (shown && GIS_PORTAL_URL && !get(mobile)) {
				showSidebar.set(true);
			}
		})
	);

	const readRatio = () => {
		try {
			const stored = Number(localStorage.getItem(RATIO_KEY));
			return stored > 0 && stored < 1 ? stored : DEFAULT_RATIO;
		} catch {
			return DEFAULT_RATIO;
		}
	};

	let ratio = readRatio();

	$: room = innerWidth - ($showSidebar ? $sidebarWidth : COLLAPSED_SIDEBAR_WIDTH);
	$: maxWidth = Math.max(MIN_WIDTH, room - MIN_CHAT_WIDTH);

	let width = 0;
	$: if (!resizingPortal) {
		width = Math.min(maxWidth, Math.max(MIN_WIDTH, Math.round(ratio * room)));
	}

	const rememberRatio = () => {
		ratio = width / room;
		try {
			localStorage.setItem(RATIO_KEY, String(ratio));
		} catch {
			// storage unavailable: the share lasts for this page only
		}
	};

	// Pages that render the chat with its navbar toggle. Elsewhere the panel is
	// hidden rather than destroyed, so the portal keeps its state across a
	// visit to the workspace.
	$: onChatRoute = $page.url.pathname === '/' || /^\/(c|folders)\//.test($page.url.pathname);

	// Created on first show and never destroyed afterwards: hiding the panel
	// must not close the portal's WebSocket, or the assistant would lose the
	// window it is talking to. Hidden, the portal can still ask to be shown.
	let mounted = false;
	$: if ($gisPortalVisible) mounted = true;
	$: shown = $gisPortalVisible && onChatRoute;

	// ------------------------------------------------ bridge with the portal
	const darkTheme = () => document.documentElement.classList.contains('dark');
	const sendContext = () => postToPortal(frame, 'gis-portal:context', { chatId: $chatId || null });
	const sendVisibility = () => postToPortal(frame, 'gis-portal:visibility', { visible: shown });
	const sendTheme = () =>
		postToPortal(frame, 'gis-portal:theme', { mode: darkTheme() ? 'dark' : 'light' });

	$: if (frame) postToPortal(frame, 'gis-portal:context', { chatId: $chatId || null });
	$: if (frame) postToPortal(frame, 'gis-portal:visibility', { visible: shown });

	async function onMessage(event: MessageEvent) {
		if (!isPortalMessage(event, frame)) return;
		const data = event.data;
		if (data.type === 'gis-portal:hello') {
			sendContext();
			sendVisibility();
			sendTheme();
		} else if (data.type === 'gis-portal:ticket-request') {
			const ticket = await fetchTicket();
			postToPortal(frame, 'gis-portal:ticket', { nonce: data.nonce, ticket });
			sendContext();
			sendTheme();
		} else if (data.type === 'gis-portal:show') {
			showGisPortal.set(true);
		} else if (data.type === 'gis-portal:status') {
			gisPortalLink.set({
				linked: Boolean(data.linked),
				userName: typeof data.userName === 'string' ? data.userName : null
			});
		}
	}

	onMount(() => {
		window.addEventListener('message', onMessage);
		// Geomas switches its theme with a class on <html>; the portal follows.
		const observer = new MutationObserver(() => sendTheme());
		observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
		return () => {
			window.removeEventListener('message', onMessage);
			observer.disconnect();
		};
	});
</script>

<svelte:window
	bind:innerWidth
	on:pointerdown={(e) => {
		if (e.target instanceof Element && e.target.closest(RESIZERS)) {
			dragging = true;
			resizingPortal = !!e.target.closest('#gis-portal-resizer');
		}
	}}
	on:pointerup={() => {
		if (resizingPortal) {
			rememberRatio();
			resizingPortal = false;
		}
		dragging = false;
	}}
	on:pointercancel={() => {
		resizingPortal = false;
		dragging = false;
	}}
	on:keyup={(e) => {
		if (
			(e.key === 'ArrowLeft' || e.key === 'ArrowRight') &&
			e.target instanceof Element &&
			e.target.closest('#gis-portal-resizer')
		) {
			rememberRatio();
		}
	}}
/>

{#if GIS_PORTAL_URL && !$mobile && mounted}
	<div
		class="h-full shrink-0 flex flex-row {shown ? '' : 'hidden'}"
		style="margin-left: {$showSidebar
			? 'var(--sidebar-width)'
			: '0'}; transition: margin-left 250ms cubic-bezier(0.22, 1, 0.36, 1);"
	>
		<ResizableSidePanel
			open={true}
			side="left"
			bind:width
			minWidth={MIN_WIDTH}
			{maxWidth}
			resizerId="gis-portal-resizer"
			className="h-full bg-white dark:bg-gray-900"
			onClose={() => showGisPortal.set(false)}
		>
			<div class="h-full w-full flex flex-col">
				<div
					class="flex shrink-0 items-center justify-between gap-2 py-2 px-3 text-gray-900 dark:text-white"
				>
					<a
						class="min-w-0 flex-1 truncate text-sm font-medium hover:underline"
						href={GIS_PORTAL_URL}
						target="_blank"
						rel="noopener noreferrer"
						title={$i18n.t('Open in new tab')}
					>
						{$i18n.t('Data portal')}
					</a>

					<div class="flex shrink-0 items-center gap-1">
						<Tooltip
							content={$gisPortalLink.linked
								? `${$i18n.t('Linked to portal as')} ${$gisPortalLink.userName ?? ''}`
								: $i18n.t('Not linked to portal')}
						>
							<span
								class="mx-1 block size-2 rounded-full {$gisPortalLink.linked
									? 'bg-emerald-500'
									: 'bg-gray-300 dark:bg-gray-600'}"
							></span>
						</Tooltip>

						<Tooltip content={$i18n.t('Portal home')}>
							<button
								class="flex size-6 items-center justify-center rounded-lg text-gray-500 transition hover:bg-gray-50 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200"
								aria-label={$i18n.t('Portal home')}
								on:click={() => postToPortal(frame, 'gis-portal:navigate', { hash: '#/' })}
							>
								<Home className="size-4" />
							</button>
						</Tooltip>

						<Tooltip content={$i18n.t('Close')}>
							<button
								class="flex size-6 items-center justify-center rounded-lg text-gray-500 transition hover:bg-gray-50 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200"
								aria-label={$i18n.t('Close')}
								on:click={() => showGisPortal.set(false)}
							>
								<XMark className="size-3.5" />
							</button>
						</Tooltip>
					</div>
				</div>

				<div class="relative w-full flex-1 min-h-0">
					{#if dragging}
						<div class="absolute inset-0 z-10"></div>
					{/if}

					<iframe
						bind:this={frame}
						src={GIS_PORTAL_URL}
						title={$i18n.t('Data portal')}
						class="h-full w-full border-0"
						allow="clipboard-read; clipboard-write; fullscreen"
					></iframe>
				</div>
			</div>
		</ResizableSidePanel>
	</div>
{/if}
