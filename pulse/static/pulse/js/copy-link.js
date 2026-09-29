// Copy-link button: copies the text of the element named by data-copy-target.
document.addEventListener('click', function (event) {
  var button = event.target.closest('[data-copy-target]');
  if (!button) {
    return;
  }
  var target = document.getElementById(button.dataset.copyTarget);
  var feedback = button.parentElement.querySelector('.copy-link__feedback');
  function show(text) {
    if (feedback) {
      feedback.textContent = text;
    }
  }
  var failed = 'Copy failed – select the link and copy it manually';
  if (!target || !navigator.clipboard) {
    show(failed);
    return;
  }
  navigator.clipboard.writeText(target.textContent.trim()).then(
    function () { show('Copied'); },
    function () { show(failed); }
  );
});
