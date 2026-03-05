window.addEventListener('load', () => {
    const mainForm: HTMLElement|null = document.getElementById('mainForm');
    const formTypeElement = document.querySelector('.hidden-type');
    const responseElement = document.getElementById('response');
    const logfileLink = document.getElementById('logfile_link');
    const jid = document.getElementById('jid');
    if (mainForm === null || responseElement === null || formTypeElement === null || logfileLink === null || jid === null) {
        throw Error('Something went wrong during setup.');
        return;
    }

    const successMessage = responseElement.querySelector( '.success-message' );
    const failureMessage = responseElement.querySelector( '.failure-message' );
    if ( successMessage === null || failureMessage === null ) {
        throw Error('Could not find success and failure messages');
        return;
    }

    const formType = formTypeElement.getAttribute( 'data-form-type' );
    if ( formType == null ) {
        throw Error('No form type found.')
    }

    mainForm.addEventListener('submit', function(event) {
        event.preventDefault();
        const formData = new FormData(mainForm as HTMLFormElement);
        const urlParams =  new URLSearchParams();
        let title = formData.get('title');
        let lang  = formData.get('lang');
        urlParams.append( 'title', title?.toString() ?? '' );
        urlParams.append( 'lang', lang?.toString() ?? '' );

        fetch(`/${formType}`, {
            method: 'POST',
            body: urlParams
        })
        .then(function(response) {
            return response.json();
        })
        .then(function(data) {
            if ( data['status'] && data['log_file'] ) {
                (logfileLink as HTMLAnchorElement).href = `/logs?file=${data['log_file']}`
                jid.innerText = data['jid'];
                successMessage.setAttribute("style", "");
                failureMessage.setAttribute("style", "display: none;")
            } else {
                successMessage.setAttribute("style", "display: none;");
                failureMessage.setAttribute("style", "")
            }
        })
        .catch(function(error) {
            successMessage.setAttribute("style", "display: none");
            failureMessage.setAttribute("style", "")
            console.error('Error:', error);
        });
    });
});