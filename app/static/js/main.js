// DataTables Chinese configuration
$(document).ready(function() {
    if ($.fn.dataTable) {
        $.extend($.fn.dataTable.defaults, {
            language: {
                url: 'https://cdn.datatables.net/plug-ins/1.13.7/i18n/zh-Hans.json'
            },
            pageLength: 25,
            lengthMenu: [[10, 25, 50, -1], [10, 25, 50, '全部']]
        });
    }
});

// Confirm delete handler
$(document).on('click', '.btn-delete-confirm', function(e) {
    if (!confirm('确定要删除吗？此操作不可撤销！')) {
        e.preventDefault();
        return false;
    }
});

// Auto-dismiss alerts after 5 seconds
$(document).ready(function() {
    setTimeout(function() {
        $('.alert-dismissible').fadeOut('slow');
    }, 5000);
});

// File input - show filename
$(document).on('change', '.file-input', function() {
    var fileName = $(this).val().split('\\').pop();
    $(this).closest('.input-group').find('.file-name').text(fileName || '未选择文件');
});

// Set active sidebar link based on current URL
$(document).ready(function() {
    var path = window.location.pathname;
    $('.sidebar .nav-link').each(function() {
        if ($(this).attr('href') && path.startsWith($(this).attr('href'))) {
            $(this).addClass('active');
        }
    });
});
