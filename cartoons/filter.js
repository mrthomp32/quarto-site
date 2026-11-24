// Client-side filtering for all/index.html. Without JavaScript every item stays visible.
(function () {
  var form = document.getElementById('filters');
  if (!form) return;
  var items = Array.prototype.slice.call(document.querySelectorAll('.grid li'));
  var sections = Array.prototype.slice.call(document.querySelectorAll('section.issue'));
  var count = document.getElementById('count');

  function apply() {
    var tag = form.tag.value, artist = form.artist.value, credited = form.credited.checked, n = 0;
    items.forEach(function (li) {
      var tags = (li.dataset.tags || '').split(' ');
      var artists = (li.dataset.artist || '').split(' ');
      var ok = (!tag || tags.indexOf(tag) >= 0) &&
               (!artist || artists.indexOf(artist) >= 0) &&
               (!credited || artists.indexOf('佚名') < 0);
      li.hidden = !ok;
      if (ok) n++;
    });
    sections.forEach(function (s) { s.hidden = !s.querySelector('li:not([hidden])'); });
    count.textContent = n + ' of ' + items.length;
    try {
      var p = new URLSearchParams();
      if (tag) p.set('tag', tag);
      if (artist) p.set('artist', artist);
      if (credited) p.set('credited', '1');
      history.replaceState(null, '', p.toString() ? '?' + p : location.pathname);
    } catch (e) {}
  }

  try {
    var q = new URLSearchParams(location.search);
    if (q.get('tag')) form.tag.value = q.get('tag');
    if (q.get('artist')) form.artist.value = q.get('artist');
    form.credited.checked = q.get('credited') === '1';
  } catch (e) {}
  form.addEventListener('change', apply);
  apply();
})();
