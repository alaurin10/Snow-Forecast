/** Moves an element to the end of <body> for as long as it is shown. Full-screen views use
 *  it: a card's blur (backdrop-filter) or transform makes the card the box that
 *  `position: fixed` is measured from, which would trap the view inside the card. Put it
 *  before `use:modal`, so the modal sees the element where it ends up. */
export function portal(node: HTMLElement) {
	document.body.appendChild(node);
	return { destroy: () => node.remove() };
}
