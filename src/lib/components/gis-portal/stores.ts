import { browser } from '$app/environment';
import { derived, writable } from 'svelte/store';

import { GIS_PORTAL_URL } from '$lib/constants';
import { mobile } from '$lib/stores';

const SHOW_KEY = 'showGisPortal';

const readShow = () => {
	try {
		return localStorage.getItem(SHOW_KEY) !== 'false';
	} catch {
		return true;
	}
};

// Open by default; the toggle in the chat navbar remembers the choice.
export const showGisPortal = writable<boolean>(browser ? readShow() : false);

if (browser) {
	showGisPortal.subscribe((value) => {
		try {
			localStorage.setItem(SHOW_KEY, value ? 'true' : 'false');
		} catch {
			// storage unavailable: the choice lasts for this page only
		}
	});
}

// Whether the panel takes room beside the chat. The chat tightens its
// horizontal padding while it does.
export const gisPortalVisible = derived(
	[showGisPortal, mobile],
	([$showGisPortal, $mobile]) => Boolean(GIS_PORTAL_URL) && $showGisPortal && !$mobile
);

// Whether the portal window accepted this user's ticket: only then can the
// assistant switch its screens and ask for confirmations there.
export const gisPortalLink = writable<{ linked: boolean; userName: string | null }>({
	linked: false,
	userName: null
});
