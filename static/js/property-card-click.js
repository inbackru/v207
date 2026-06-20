console.log('🔧 Property card click handler loading...');

document.addEventListener('click', function(e) {
    if (e.defaultPrevented) return;
    
    var card = e.target.closest('.property-card');
    if (!card) return;
    
    if (e.target.closest('.mobile-action-bar')) {
        return;
    }
    
    if (e.target.closest('button') || e.target.closest('a') || e.target.closest('.mobile-call-btn') || e.target.closest('.map-btn') || e.target.closest('.compare-btn') || e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') {
        return;
    }
    
    var url = card.getAttribute('data-property-url');
    if (url) {
        window.location.href = url;
    }
});

console.log('✅ Property card click handler installed');
